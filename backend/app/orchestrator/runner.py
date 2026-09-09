"""Investigation orchestrator: triage -> phase A (evidence gathering via the
`claude` CLI + MCP tools) -> phase B (schema-validated synthesis) -> guardrails
-> final Investigation. This replaces the Phase 0 wiring stub; the event
shapes it publishes are unchanged, so the frontend needed no changes.

Only this module knows how the two phases fit together. `cli_agent.py` knows
how to talk to the CLI; `evidence_mapper.py` knows how to turn a tool result
into `Evidence`; `correlate.py` knows how to score it. This module is glue.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import get_settings
from app.models.domain import (
    ActionKind,
    AgentStep,
    AgentStepStatus,
    Confidence,
    Evidence,
    Hypothesis,
    Investigation,
    InvestigationStatus,
    StreamEvent,
    StreamEventType,
    SuggestedAction,
)
from app.orchestrator import correlate
from app.orchestrator.cli_agent import ClaudeCliError, run_synthesis, stream_investigate
from app.orchestrator.evidence_mapper import bare_tool_name, map_tool_result_to_evidence
from app.orchestrator.triage import TriageResult, triage
from app.store import store

logger = logging.getLogger(__name__)

_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().max_concurrent_investigations)
    return _semaphore


async def run_investigation(investigation_id: str) -> None:
    async with _get_semaphore():
        investigation = store.get(investigation_id)
        if investigation is None:
            return

        settings = get_settings()
        if settings.data_source != "mock":
            await _fail(investigation, "DATA_SOURCE=live is not implemented yet (Phase 7).")
            return
        if not investigation.alert.scenario:
            await _fail(
                investigation,
                "This alert has no `scenario` set. The mock data layer can only serve "
                "fixture-backed scenarios (see app/fixtures/scenarios) until Phase 7 adds a "
                "live GitHub/observability adapter.",
            )
            return

        workdir = Path(tempfile.mkdtemp(prefix="sre-investigator-"))
        started = time.monotonic()
        try:
            await _run(investigation, workdir)
        except Exception as e:  # noqa: BLE001 - top-level guard, must never crash the task
            logger.exception("Investigation %s crashed", investigation_id)
            await _fail(investigation, f"Unexpected error: {e}")
        finally:
            investigation.wall_time_ms = int((time.monotonic() - started) * 1000)
            store.update(investigation)
            shutil.rmtree(workdir, ignore_errors=True)


async def _run(investigation: Investigation, workdir: Path) -> None:
    settings = get_settings()
    alert = investigation.alert
    assert alert.scenario is not None  # checked by the caller before spawning this
    session_id = str(uuid4())
    store.set_session(investigation.id, session_id)
    mcp_config_path = _write_mcp_config(workdir, alert.scenario, alert.fired_at)

    await _set_status(investigation, InvestigationStatus.triaging)
    t = triage(alert)

    await _set_status(investigation, InvestigationStatus.investigating)
    prompt = _phase_a_prompt(investigation, t)

    pending: dict[str, AgentStep] = {}
    pending_input: dict[str, dict[str, object]] = {}
    tool_call_count = 0
    budget_exceeded = False

    events = stream_investigate(
        prompt=prompt,
        mcp_config_path=str(mcp_config_path),
        session_id=session_id,
        timeout_s=settings.investigation_timeout_s,
    )
    try:
        async for event in events:
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        tool_call_count += 1
            await _handle_stream_event(event, investigation, pending, pending_input)
            if tool_call_count >= settings.max_tool_calls:
                # Cut the stream short rather than letting a looping agent run to the
                # wall-clock timeout — synthesize on whatever evidence exists so far
                # (see the warning appended after _apply_synthesis below).
                budget_exceeded = True
                break
    except ClaudeCliError as e:
        await _resolve_orphaned_steps(
            investigation, pending, "Investigation ended before this call returned"
        )
        await _fail(investigation, f"Evidence gathering failed: {e}")
        return
    finally:
        # Deterministic cleanup of the CLI subprocess on the budget-exceeded early-exit
        # path above — see stream_investigate's own finally block in cli_agent.py, which
        # this .aclose() triggers via GeneratorExit. A no-op if the stream already ended
        # naturally or raised.
        await events.aclose()

    # A tool_use with no matching tool_result (stream ended mid-call) would otherwise
    # leave its AgentStep at status=running forever, showing a permanent spinner on a
    # finished investigation.
    await _resolve_orphaned_steps(
        investigation, pending, "No result received before the stream ended"
    )

    await _set_status(investigation, InvestigationStatus.synthesizing)

    evidence_by_id = {e.id: e for e in investigation.evidence}
    schema = _synthesis_schema(list(evidence_by_id))
    synthesis_prompt = _phase_b_prompt(investigation.evidence)

    try:
        result = await run_synthesis(
            prompt=synthesis_prompt,
            mcp_config_path=str(mcp_config_path),
            session_id=session_id,
            json_schema=schema,
            timeout_s=settings.investigation_timeout_s,
        )
    except ClaudeCliError as e:
        investigation.tldr = "Automated synthesis failed; raw evidence is available below."
        investigation.status = InvestigationStatus.needs_input
        investigation.error = str(e)
        store.update(investigation)
        await store.publish(
            investigation.id,
            StreamEvent(
                type=StreamEventType.investigation_complete,
                investigation_id=investigation.id,
                payload=investigation.model_dump(mode="json"),
            ).model_dump(mode="json"),
        )
        return

    investigation.total_cost_usd += result.total_cost_usd
    _apply_synthesis(investigation, result.structured_output, evidence_by_id)
    if budget_exceeded:
        # Appended after _apply_synthesis, which assigns investigation.warnings from
        # correlate.grounding_warnings() — appending here (not before) is what keeps
        # this from being silently overwritten.
        investigation.warnings.append(
            f"Investigation stopped after reaching the {settings.max_tool_calls}-tool-call "
            "budget. The hypothesis below is based on the evidence gathered up to that "
            "point, not necessarily an exhaustive investigation."
        )

    investigation.status = InvestigationStatus.complete
    investigation.completed_at = datetime.now(UTC)
    store.update(investigation)
    await store.publish(
        investigation.id,
        StreamEvent(
            type=StreamEventType.investigation_complete,
            investigation_id=investigation.id,
            payload=investigation.model_dump(mode="json"),
        ).model_dump(mode="json"),
    )


class NoActiveSessionError(Exception):
    """Raised when a follow-up question is asked against an investigation with no
    resumable `claude` CLI session — either it predates this server process (loaded
    from a browser's IndexedDB after a restart) or it never ran against the CLI at
    all (e.g. an alert with no matching scenario, which fails before any session is
    created)."""


async def ask_follow_up(investigation: Investigation, question: str) -> dict[str, Any]:
    """Resumes the investigation's original CLI session to answer a free-text
    question against the evidence it already gathered — no new tool calls, just
    reasoning over context the model already has. Returns a dict matching
    `AskFollowUpResponse` (answer, cited_evidence_ids)."""
    settings = get_settings()
    session_id = store.get_session(investigation.id)
    if session_id is None:
        raise NoActiveSessionError

    assert investigation.alert.scenario is not None
    workdir = Path(tempfile.mkdtemp(prefix="sre-investigator-followup-"))
    try:
        mcp_config_path = _write_mcp_config(
            workdir, investigation.alert.scenario, investigation.alert.fired_at
        )
        evidence_by_id = {e.id: e for e in investigation.evidence}
        manifest = "\n".join(
            f"- id={e.id} [{e.kind.value}] {e.title}: {e.summary}" for e in investigation.evidence
        ) or "(no evidence was gathered)"
        prompt = f"""A follow-up question about the investigation you already completed:

{question}

Evidence available (cite ONLY these ids in cited_evidence_ids, exactly as written, and only
the ones actually relevant to this answer):
{manifest}

Answer directly and concisely. If you need to check something you didn't already look at, you
may use your tools, but prefer answering from what you already found."""

        schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "cited_evidence_ids": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(evidence_by_id)} if evidence_by_id
                    else {"type": "string"},
                },
            },
            "required": ["answer", "cited_evidence_ids"],
        }

        result = await run_synthesis(
            prompt=prompt,
            mcp_config_path=str(mcp_config_path),
            session_id=session_id,
            json_schema=schema,
            timeout_s=settings.investigation_timeout_s,
        )
        # A follow-up spends real credit against the same investigation, so it belongs
        # in that investigation's running total rather than being invisible.
        investigation.total_cost_usd += result.total_cost_usd
        store.update(investigation)

        cited = [
            eid for eid in result.structured_output.get("cited_evidence_ids", [])
            if eid in evidence_by_id
        ]
        return {"answer": result.structured_output.get("answer", ""), "cited_evidence_ids": cited}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def _handle_stream_event(
    event: dict[str, Any],
    investigation: Investigation,
    pending: dict[str, AgentStep],
    pending_input: dict[str, dict[str, object]],
) -> None:
    event_type = event.get("type")

    if event_type == "assistant":
        for block in event.get("message", {}).get("content", []):
            block_type = block.get("type")
            if block_type == "tool_use":
                tool_id = block.get("id")
                name = bare_tool_name(block.get("name", ""))
                tool_input = block.get("input", {})
                step = AgentStep(
                    label=f"{name}({_format_args(tool_input)})",
                    tool_name=name,
                    tool_input=tool_input,
                    status=AgentStepStatus.running,
                    started_at=datetime.now(UTC),
                )
                investigation.steps.append(step)
                pending[tool_id] = step
                pending_input[tool_id] = tool_input
                store.update(investigation)
                await _publish_step(investigation, StreamEventType.step_started, step)
            elif block_type == "text" and block.get("text", "").strip():
                narration = AgentStep(
                    label=block["text"].strip(),
                    status=AgentStepStatus.complete,
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                )
                investigation.steps.append(narration)
                store.update(investigation)
                await _publish_step(investigation, StreamEventType.step_finished, narration)

    elif event_type == "user":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") != "tool_result":
                continue
            tool_id = block.get("tool_use_id")
            if tool_id not in pending:
                continue
            step = pending.pop(tool_id)
            tool_input = pending_input.pop(tool_id, {})

            output = _unwrap_tool_result(block.get("content"))
            is_error = bool(block.get("is_error"))
            step.finished_at = datetime.now(UTC)
            investigation.total_tool_calls += 1

            new_evidence: list[Evidence] = []
            if is_error:
                step.status = AgentStepStatus.error
                step.error = str(output)[:500]
            else:
                step.status = AgentStepStatus.complete
                new_evidence = map_tool_result_to_evidence(step.tool_name or "", tool_input, output)
                investigation.evidence.extend(new_evidence)
                step.evidence_ids = [e.id for e in new_evidence]
                step.tool_output_summary = _summarize_output(output)

            store.update(investigation)
            await _publish_step(investigation, StreamEventType.step_finished, step, new_evidence)

    elif event_type == "result":
        # The final stream-json event carries phase A's cost. Without this the cost
        # footer only ever showed phase B's synthesis call — a large under-report,
        # since phase A is where every tool-calling turn happens.
        investigation.total_cost_usd += float(event.get("total_cost_usd") or 0.0)
        store.update(investigation)


async def _publish_step(
    investigation: Investigation,
    event_type: StreamEventType,
    step: AgentStep,
    new_evidence: list[Evidence] | None = None,
) -> None:
    """Every step event carries any newly-created Evidence inline, not just IDs —
    otherwise the frontend would need a full re-fetch to render the evidence rail
    as it streams in."""
    await store.publish(
        investigation.id,
        StreamEvent(
            type=event_type,
            investigation_id=investigation.id,
            payload={
                "step": step.model_dump(mode="json"),
                "new_evidence": [e.model_dump(mode="json") for e in new_evidence or []],
            },
        ).model_dump(mode="json"),
    )


async def _resolve_orphaned_steps(
    investigation: Investigation, pending: dict[str, AgentStep], reason: str
) -> None:
    """Marks any tool_use whose tool_result never arrived as errored rather than
    leaving it at status=running forever (a permanent spinner on a finished
    investigation). Does not touch `pending` itself — the caller is done with it
    either way once this runs."""
    for step in pending.values():
        step.status = AgentStepStatus.error
        step.error = reason
        step.finished_at = datetime.now(UTC)
        await _publish_step(investigation, StreamEventType.step_finished, step)
    store.update(investigation)


def _unwrap_tool_result(content: object) -> object:
    """MCP tool results arrive JSON-encoded, often wrapped as {"result": ...}
    for non-dict return values (see mcp_server/server.py). Isolated here since
    it's a CLI/MCP serialization detail, not orchestration logic."""
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content
        if isinstance(parsed, dict) and set(parsed) == {"result"}:
            return parsed["result"]
        return parsed
    return content


def _format_args(tool_input: dict[str, object]) -> str:
    parts = [f"{k}={v}" for k, v in list(tool_input.items())[:3]]
    return ", ".join(parts)


def _summarize_output(output: object) -> str:
    if isinstance(output, list):
        return f"{len(output)} result(s)"
    if isinstance(output, dict):
        return json.dumps(output)[:200]
    return str(output)[:200]


def _write_mcp_config(workdir: Path, scenario_key: str, reference_time: datetime) -> Path:
    backend_root = Path(__file__).resolve().parents[2]
    settings = get_settings()
    env = {
        "SRE_SCENARIO_KEY": scenario_key,
        "SRE_REFERENCE_TIME": reference_time.isoformat(),
        "SRE_OBSERVABILITY_DATA_SOURCE": settings.observability_data_source,
    }
    if settings.observability_data_source == "live":
        env["SRE_PROMETHEUS_URL"] = settings.prometheus_url
        env["SRE_LOKI_URL"] = settings.loki_url
        if settings.glitchtip_url:
            env["SRE_GLITCHTIP_URL"] = settings.glitchtip_url
        if settings.glitchtip_api_token:
            env["SRE_GLITCHTIP_API_TOKEN"] = settings.glitchtip_api_token
        if settings.glitchtip_org_slug:
            env["SRE_GLITCHTIP_ORG_SLUG"] = settings.glitchtip_org_slug
        if settings.glitchtip_project_slug:
            env["SRE_GLITCHTIP_PROJECT_SLUG"] = settings.glitchtip_project_slug

    config = {
        "mcpServers": {
            "sre_tools": {
                "command": str(backend_root / ".venv" / "bin" / "python"),
                "args": [str(backend_root / "app" / "mcp_server" / "server.py")],
                "env": env,
            }
        }
    }
    path = workdir / "mcp_config.json"
    path.write_text(json.dumps(config))
    return path


def _phase_a_prompt(investigation: Investigation, t: TriageResult) -> str:
    alert = investigation.alert
    budget = get_settings().max_tool_calls
    return f"""You are an SRE investigating a production alert. Use your tools to gather
evidence about the root cause. Do NOT give your final conclusion yet — a follow-up prompt
will ask for that. For now, just investigate thoroughly.

Alert:
- service: {alert.service}
- severity: {alert.severity.value}
- title: {alert.title}
- message: {alert.message}
- stack_trace: {alert.stack_trace or "(none provided)"}
- fired_at: {alert.fired_at.isoformat()}

Suggested starting window (narrow): {t.narrow_since.isoformat()} to {t.narrow_until.isoformat()}
Suggested fallback window (wide, use if the narrow window doesn't explain it): \
{t.wide_since.isoformat()} to {t.wide_until.isoformat()}

{t.playbook.hint}

Investigate efficiently: aim to reach a well-evidenced conclusion within roughly {budget} tool
calls rather than exhaustively checking everything available. If you're not converging by then,
stop and rely on your strongest evidence so far rather than continuing to search.

All tool timestamps must be ISO 8601 with timezone offset, matching the formats above.
Investigate using the available tools before responding."""


def _phase_b_prompt(evidence: list[Evidence]) -> str:
    manifest = "\n".join(
        f"- id={e.id} [{e.kind.value}] {e.title}: {e.summary}" for e in evidence
    ) or "(no evidence was gathered)"
    return f"""Based on everything you found, give your final root-cause analysis now.

Evidence you gathered (cite ONLY these ids in evidence_ids, exactly as written):
{manifest}

If the evidence is insufficient for a confident conclusion, say so explicitly in the
hypothesis summary and use confidence="low" rather than guessing.

For each suggested_action, include a concrete, copy-pasteable `command` whenever one
naturally applies to THIS specific incident (e.g. a git revert of the actual commit sha, a
kubectl rollout/scale command against the actual service name, a curl against the actual
endpoint, a specific metric query) — using the real identifiers from the evidence above, not
placeholders. Only leave `command` null when the action genuinely isn't a single runnable
command (e.g. "page the on-call database owner")."""


def _synthesis_schema(evidence_ids: list[str]) -> dict[str, Any]:
    evidence_id_schema: dict[str, Any] = (
        {"type": "string", "enum": evidence_ids} if evidence_ids else {"type": "string"}
    )
    return {
        "type": "object",
        "properties": {
            "tldr": {"type": "string"},
            "hypotheses": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "reasoning": {"type": "string"},
                        "confidence": {"type": "string", "enum": [c.value for c in Confidence]},
                        "evidence_ids": {"type": "array", "items": evidence_id_schema},
                        "suggested_actions": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": [k.value for k in ActionKind],
                                    },
                                    "title": {"type": "string"},
                                    "description": {"type": "string"},
                                    "command": {
                                        "type": ["string", "null"],
                                        "description": (
                                            "A concrete, copy-pasteable command using this "
                                            "incident's real identifiers (commit sha, service "
                                            "name, PR number, etc.), or null if this action "
                                            "isn't expressible as one command."
                                        ),
                                    },
                                },
                                "required": ["kind", "title", "description", "command"],
                            },
                        },
                    },
                    "required": [
                        "summary",
                        "reasoning",
                        "confidence",
                        "evidence_ids",
                        "suggested_actions",
                    ],
                },
            },
        },
        "required": ["tldr", "hypotheses"],
    }


def _parse_action(a: dict[str, Any]) -> SuggestedAction | None:
    try:
        return SuggestedAction(
            kind=ActionKind(a["kind"]),
            title=a["title"],
            description=a["description"],
            command=a.get("command"),
        )
    except (KeyError, ValueError) as e:
        # A malformed action from the model (unknown `kind`, missing field) is worth
        # dropping, not worth losing the entire completed investigation over — see
        # PLAN.md's review-pass notes on the Phase 4 suggested_actions regression.
        logger.warning("Dropping malformed suggested_action %r: %s", a, e)
        return None


def _parse_hypothesis(
    rank: int, raw: dict[str, Any], evidence_by_id: dict[str, Evidence]
) -> Hypothesis:
    # Defense in depth: the schema enum should already guarantee this, but a model
    # can still be resumed against a stale/mismatched schema in edge cases.
    valid_ids = [eid for eid in raw.get("evidence_ids", []) if eid in evidence_by_id]
    actions = [a for a in (_parse_action(a) for a in raw.get("suggested_actions", [])) if a]
    try:
        confidence = Confidence(raw.get("confidence", "low"))
    except ValueError:
        confidence = Confidence.low
    return Hypothesis(
        rank=rank,
        summary=raw.get("summary", ""),
        reasoning=raw.get("reasoning", ""),
        confidence=confidence,
        evidence_ids=valid_ids,
        suggested_actions=actions,
    )


def _apply_synthesis(
    investigation: Investigation, structured: dict[str, Any], evidence_by_id: dict[str, Evidence]
) -> None:
    investigation.tldr = structured.get("tldr", "")
    hypotheses = [
        _parse_hypothesis(rank, raw, evidence_by_id)
        for rank, raw in enumerate(structured.get("hypotheses", []), start=1)
    ]

    investigation.hypotheses = hypotheses

    scored = correlate.rank_evidence(investigation.evidence, investigation.alert)
    investigation.warnings = correlate.grounding_warnings(hypotheses, scored)


async def _set_status(investigation: Investigation, status: InvestigationStatus) -> None:
    investigation.status = status
    store.update(investigation)
    await store.publish(
        investigation.id,
        StreamEvent(
            type=StreamEventType.status_changed,
            investigation_id=investigation.id,
            payload={"status": status.value},
        ).model_dump(mode="json"),
    )


async def _fail(investigation: Investigation, message: str) -> None:
    investigation.status = InvestigationStatus.failed
    investigation.error = message
    store.update(investigation)
    await store.publish(
        investigation.id,
        StreamEvent(
            type=StreamEventType.investigation_failed,
            investigation_id=investigation.id,
            payload=investigation.model_dump(mode="json"),
        ).model_dump(mode="json"),
    )
