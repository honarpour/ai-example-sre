"""The only module allowed to spawn or parse output from the `claude` CLI.

Everything downstream (the runner, triage, synthesis) talks to this module's
functions and never touches subprocess/NDJSON details directly — if the CLI's
output format changes, this is the one file that needs to change.

Three call shapes:

- `stream_investigate()`: phase A, evidence gathering. Runs with
  `--output-format stream-json` and yields parsed event dicts as they arrive,
  so the caller can publish live progress over SSE. Freeform — no schema.
- `run_synthesis()`: phase B, final answer. Resumes the same CLI session with
  `--output-format json` and a caller-supplied `--json-schema`, returning the
  schema-validated `structured_output` dict directly. Because the schema's
  evidence_id enum is built from evidence phase A actually produced, a
  citation that doesn't exist is a schema violation, not just a bad look —
  see runner.py's evidence-ID enum construction.
- `run_isolated_json()`: a one-off schema-validated call with no MCP server and
  no session to resume — used by the eval harness's LLM-judge (see
  evals/judge.py), which only needs to compare two pieces of text, not
  investigate anything.

Safety posture (validated live against this exact CLI build — see PLAN.md
Phase 1/2 findings): `--strict-mcp-config` limits the agent to *only* the MCP
server we hand it (no other project MCP servers are reachable), and
`--disallowedTools` genuinely removes built-in tools from the tool set
entirely (confirmed: a disallowed Bash tool doesn't exist to the model at
all, it isn't just permission-denied). Every method here disallows
Bash/Edit/Write/NotebookEdit/Task/WebFetch/WebSearch unconditionally — this
agent is read-only by construction. The MCP tools themselves are safe to
leave otherwise unrestricted because every one of them is a read-only query
(see app/sources/base.py) — there is nothing dangerous to additionally scope.

Auth mode (PLAN.md Phase 7d): when `ANTHROPIC_API_KEY` is configured, every
call adds `--bare` — a minimal-footprint mode that skips the full Claude Code
system prompt/hooks/plugins and requires API-key auth rather than the CLI's
interactive OAuth login. NOTE: `--bare` + `--mcp-config` together is
implemented per the CLI's own `--help` text (both are explicitly listed as
compatible with `--bare`) but has NOT been live-verified end-to-end the way
everything else in this file has — this repo's OAuth session can't exercise
the API-key code path. Verify against a real key before relying on it.

Cost note: phase A and phase B can run different models (`CLAUDE_MODEL_PHASE_A`
vs `CLAUDE_MODEL`, see config.py) — phase A is mechanical tool orchestration,
not the reasoning step being graded, so a cheaper/faster model there doesn't
touch phase B's quality. `stream_investigate` also cleans up its subprocess if
the caller stops consuming events early (runner.py's tool-call budget) rather
than orphaning it — see the `finally` block below.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.config import get_settings

logger = logging.getLogger(__name__)

_DISALLOWED_TOOLS = "Bash,Edit,Write,NotebookEdit,Task,WebFetch,WebSearch"


class ClaudeCliError(Exception):
    """Raised when the `claude` CLI process fails, times out, or produces
    output we can't parse. Callers should treat this as a failed investigation
    step, not a bug to propagate as a 500."""


@dataclass
class SynthesisResult:
    structured_output: dict[str, Any]
    total_cost_usd: float
    duration_ms: int
    num_turns: int


def _bare_mode_args() -> list[str]:
    return ["--bare"] if get_settings().anthropic_api_key else []


def _base_args(
    *, mcp_config_path: str, session_id: str, resume: bool, model: str | None = None
) -> list[str]:
    settings = get_settings()
    args = [
        settings.claude_binary,
        "--print",
        "--resume" if resume else "--session-id",
        session_id,
        *_bare_mode_args(),
        "--mcp-config",
        mcp_config_path,
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--disallowedTools",
        _DISALLOWED_TOOLS,
        "--permission-mode",
        "bypassPermissions",
    ]
    if model:
        args += ["--model", model]
    return args


async def stream_investigate(
    *, prompt: str, mcp_config_path: str, session_id: str, timeout_s: int
) -> AsyncGenerator[dict[str, Any], None]:
    """Phase A: run the investigation prompt, yielding each parsed stream-json
    event as it arrives. Raises `ClaudeCliError` on a non-zero exit or a
    malformed line; a timeout kills the process and raises as well.

    Declared as `AsyncGenerator` rather than `AsyncIterator` specifically so a
    caller that stops consuming early (runner.py's tool-call budget) can call
    `.aclose()` on it deterministically — see the `finally` block below, which
    is what actually kills the subprocess in that case."""
    settings = get_settings()
    model = settings.claude_model_phase_a or settings.claude_model
    args = _base_args(
        mcp_config_path=mcp_config_path, session_id=session_id, resume=False, model=model
    )
    args += ["--output-format", "stream-json", "--verbose", prompt]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    stdout = proc.stdout

    async def _read_lines() -> AsyncGenerator[dict[str, Any], None]:
        async for raw_line in stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed stream-json line: %r", line[:200])

    returncode: int | None = None
    try:
        try:
            async with asyncio.timeout(timeout_s):
                async for event in _read_lines():
                    yield event
                returncode = await proc.wait()
        except TimeoutError as e:
            proc.kill()
            await proc.wait()
            raise ClaudeCliError(f"claude CLI timed out after {timeout_s}s") from e
    finally:
        # If we get here with the process still running, the consumer stopped iterating
        # early (GeneratorExit from an explicit .aclose(), e.g. runner.py hitting its
        # tool-call budget) rather than the stream ending naturally or timing out above.
        # Without this, that subprocess would be silently orphaned — still running,
        # still burning real API cost, for output nobody will ever read.
        if proc.returncode is None:
            proc.kill()
            await proc.wait()

    if returncode is not None and returncode != 0:
        stderr = (await proc.stderr.read()).decode("utf-8", errors="replace") if proc.stderr else ""
        raise ClaudeCliError(f"claude CLI exited {returncode}: {stderr[:1000]}")


async def run_synthesis(
    *,
    prompt: str,
    mcp_config_path: str,
    session_id: str,
    json_schema: dict[str, Any],
    timeout_s: int,
) -> SynthesisResult:
    """Phase B: resume the phase-A session and demand a schema-validated final
    answer. Raises `ClaudeCliError` if the process fails or the CLI reports
    `is_error` (which includes schema-validation failure). Deliberately uses
    `claude_model` (the full-quality model), not `claude_model_phase_a` — this
    is the reasoning step actually being graded, unlike phase A's tool-calling."""
    settings = get_settings()
    args = _base_args(
        mcp_config_path=mcp_config_path,
        session_id=session_id,
        resume=True,
        model=settings.claude_model,
    )
    args += [
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(json_schema),
        prompt,
    ]

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout_s,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError as e:
        raise ClaudeCliError(f"claude CLI synthesis timed out after {timeout_s}s") from e

    if proc.returncode != 0:
        raise ClaudeCliError(
            f"claude CLI synthesis exited {proc.returncode}: "
            f"{stderr.decode('utf-8', errors='replace')[:1000]}"
        )

    try:
        result = json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise ClaudeCliError(f"claude CLI synthesis produced invalid JSON: {e}") from e

    if result.get("is_error"):
        raise ClaudeCliError(f"claude CLI synthesis reported an error: {result.get('result')}")

    structured = result.get("structured_output")
    if structured is None:
        raise ClaudeCliError("claude CLI synthesis did not return structured_output")

    return SynthesisResult(
        structured_output=structured,
        total_cost_usd=result.get("total_cost_usd", 0.0),
        duration_ms=result.get("duration_ms", 0),
        num_turns=result.get("num_turns", 0),
    )


async def run_isolated_json(
    *, prompt: str, json_schema: dict[str, Any], timeout_s: int
) -> SynthesisResult:
    """A single schema-validated call with no MCP server, no tools, and no
    session — a fresh, isolated turn. `--strict-mcp-config` with no
    `--mcp-config` at all means zero MCP servers are reachable."""
    settings = get_settings()
    args = [
        settings.claude_binary,
        "--print",
        "--session-id",
        str(uuid4()),
        *_bare_mode_args(),
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--disallowedTools",
        _DISALLOWED_TOOLS,
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(json_schema),
    ]
    if settings.claude_model:
        args += ["--model", settings.claude_model]
    args.append(prompt)

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout_s,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError as e:
        raise ClaudeCliError(f"claude CLI judge call timed out after {timeout_s}s") from e

    if proc.returncode != 0:
        raise ClaudeCliError(
            f"claude CLI judge call exited {proc.returncode}: "
            f"{stderr.decode('utf-8', errors='replace')[:1000]}"
        )

    try:
        result = json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise ClaudeCliError(f"claude CLI judge call produced invalid JSON: {e}") from e

    if result.get("is_error"):
        raise ClaudeCliError(f"claude CLI judge call reported an error: {result.get('result')}")

    structured = result.get("structured_output")
    if structured is None:
        raise ClaudeCliError("claude CLI judge call did not return structured_output")

    return SynthesisResult(
        structured_output=structured,
        total_cost_usd=result.get("total_cost_usd", 0.0),
        duration_ms=result.get("duration_ms", 0),
        num_turns=result.get("num_turns", 0),
    )
