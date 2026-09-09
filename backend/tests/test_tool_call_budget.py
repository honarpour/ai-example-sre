"""Regression tests for the phase A tool-call budget (a cost/perf guard added after a
review pass): if the agent keeps calling tools past `settings.max_tool_calls`, the stream
should be cut short — synthesizing on whatever evidence exists rather than running to the
120s wall-clock timeout — and the CLI subprocess feeding it should be closed deterministically
rather than left running. `stream_investigate` and `run_synthesis` are faked here; nothing
spawns the real `claude` CLI.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

from app.config import get_settings
from app.models.domain import Alert, AlertSource, Investigation, Severity
from app.orchestrator import runner
from app.orchestrator.cli_agent import SynthesisResult
from app.store import store


def _investigation() -> Investigation:
    alert = Alert(
        title="t", service="payments-api", severity=Severity.high, message="m",
        fired_at=datetime.now(UTC), source=AlertSource.manual, scenario="bad-deploy",
    )
    inv = Investigation(alert=alert, created_at=datetime.now(UTC))
    store.create(inv)
    return inv


def _many_tool_call_events(n: int, closed: list[bool]) -> AsyncGenerator[dict[str, Any], None]:
    """A fake phase-A stream that would yield `n` tool_use/tool_result pairs if fully
    consumed. `closed` records whether the generator was torn down early (via aclose(),
    i.e. GeneratorExit) rather than exhausted normally."""
    pairs_yielded = 0

    async def gen() -> AsyncGenerator[dict[str, Any], None]:
        nonlocal pairs_yielded
        try:
            for i in range(n):
                tool_id = f"tool_{i}"
                yield {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": tool_id,
                                "name": "github_get_deploys",
                                "input": {},
                            }
                        ]
                    },
                }
                yield {
                    "type": "user",
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": tool_id, "content": "[]"}
                        ]
                    },
                }
                pairs_yielded += 1
            yield {"type": "result", "subtype": "success", "total_cost_usd": 0.1}
        finally:
            if pairs_yielded < n:
                closed[0] = True

    return gen()


async def test_stream_cut_short_at_tool_call_budget(monkeypatch):
    monkeypatch.setenv("MAX_TOOL_CALLS", "3")
    get_settings.cache_clear()
    try:
        closed = [False]
        fake_stream = _many_tool_call_events(50, closed)
        monkeypatch.setattr(runner, "stream_investigate", lambda **kw: fake_stream)
        monkeypatch.setattr(
            runner,
            "run_synthesis",
            AsyncMock(
                return_value=SynthesisResult(
                    structured_output={
                        "tldr": "t",
                        "hypotheses": [
                            {
                                "summary": "s", "reasoning": "r", "confidence": "low",
                                "evidence_ids": [], "suggested_actions": [],
                            }
                        ],
                    },
                    total_cost_usd=0.05,
                    duration_ms=1,
                    num_turns=1,
                )
            ),
        )

        inv = _investigation()
        await runner.run_investigation(inv.id)

        result = store.get(inv.id)
        assert result is not None
        assert result.status.value == "complete"
        assert any("tool-call budget" in w for w in result.warnings)
        assert closed[0] is True  # the 50-event stream was torn down, not exhausted
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


async def test_no_warning_when_budget_not_hit(monkeypatch):
    get_settings.cache_clear()
    try:
        closed = [False]
        fake_stream = _many_tool_call_events(2, closed)
        monkeypatch.setattr(runner, "stream_investigate", lambda **kw: fake_stream)
        monkeypatch.setattr(
            runner,
            "run_synthesis",
            AsyncMock(
                return_value=SynthesisResult(
                    structured_output={
                        "tldr": "t",
                        "hypotheses": [
                            {
                                "summary": "s", "reasoning": "r", "confidence": "low",
                                "evidence_ids": [], "suggested_actions": [],
                            }
                        ],
                    },
                    total_cost_usd=0.05,
                    duration_ms=1,
                    num_turns=1,
                )
            ),
        )

        inv = _investigation()
        await runner.run_investigation(inv.id)

        result = store.get(inv.id)
        assert result is not None
        assert not any("tool-call budget" in w for w in result.warnings)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
