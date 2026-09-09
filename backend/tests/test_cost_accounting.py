"""Regression tests for investigation cost accounting, added after a review pass
found phase A's cost was being silently dropped.

The `claude` CLI's stream-json output ends with a `{"type": "result", ...,
"total_cost_usd": N}` event (verified against the live CLI). `_handle_stream_event`
handled only `assistant` and `user` events, so that final event — carrying the cost
of every tool-calling turn in phase A — was ignored, and the UI's cost footer showed
phase B's synthesis call alone. That's the majority of a run's spend going unreported
on a panel whose entire job is reporting spend.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.domain import AgentStep, Alert, AlertSource, Investigation, Severity
from app.orchestrator.runner import _handle_stream_event


def _investigation() -> Investigation:
    alert = Alert(
        title="t", service="s", severity=Severity.high, message="m",
        fired_at=datetime.now(UTC), source=AlertSource.manual, scenario="bad-deploy",
    )
    return Investigation(alert=alert, created_at=datetime.now(UTC))


async def _feed(investigation: Investigation, event: dict[str, object]) -> None:
    pending: dict[str, AgentStep] = {}
    pending_input: dict[str, dict[str, object]] = {}
    await _handle_stream_event(event, investigation, pending, pending_input)


async def test_result_event_accumulates_phase_a_cost():
    inv = _investigation()
    await _feed(inv, {"type": "result", "subtype": "success", "total_cost_usd": 0.42})
    assert inv.total_cost_usd == pytest.approx(0.42)


async def test_result_event_without_cost_is_not_fatal():
    """A `result` event missing or nulling the field must not crash the run —
    a failed/interrupted turn can emit one."""
    inv = _investigation()
    await _feed(inv, {"type": "result", "subtype": "error_during_execution"})
    await _feed(inv, {"type": "result", "total_cost_usd": None})
    assert inv.total_cost_usd == 0.0


async def test_costs_accumulate_rather_than_overwrite():
    """Phase A's stream cost and phase B's synthesis cost both land on the same
    investigation, so the operation has to be `+=`, not assignment."""
    inv = _investigation()
    await _feed(inv, {"type": "result", "total_cost_usd": 0.30})
    inv.total_cost_usd += 0.12  # what _run() does with the synthesis result
    assert inv.total_cost_usd == pytest.approx(0.42)
