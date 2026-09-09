"""End-to-end tests that actually spawn the `claude` CLI and spend real API
credit (~$0.25-0.30 and ~70-100s each, as measured). Skipped by default —
run explicitly with RUN_LIVE_LLM_TESTS=1 when validating orchestrator changes
against the real CLI, not on every `pytest` invocation.

These are the only tests that exercise the full two-phase pipeline
(cli_agent -> runner -> evidence_mapper -> correlate) against a real model;
everything else in this suite is deterministic and fast by design.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from app.models.domain import Alert, AlertSource, Investigation, InvestigationStatus, Severity
from app.orchestrator.runner import ask_follow_up, run_investigation
from app.store import store

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="set RUN_LIVE_LLM_TESTS=1 to run (spawns the real claude CLI, costs real credit)",
)


async def _run_scenario(scenario_key: str, **alert_kwargs: object) -> Investigation:
    alert = Alert(
        fired_at=datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC),
        source=AlertSource.manual,
        scenario=scenario_key,
        **alert_kwargs,  # type: ignore[arg-type]
    )
    investigation = Investigation(alert=alert, created_at=datetime.now(UTC))
    store.create(investigation)
    await run_investigation(investigation.id)
    result = store.get(investigation.id)
    assert result is not None
    return result


async def test_bad_deploy_identifies_pool_shrink_pr():
    result = await _run_scenario(
        "bad-deploy",
        title="High error rate: payments-api",
        service="payments-api",
        severity=Severity.critical,
        message="5xx error rate for payments-api exceeded 8% threshold.",
        stack_trace="sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 0 reached",
    )
    assert result.status == InvestigationStatus.complete
    assert result.hypotheses
    top = min(result.hypotheses, key=lambda h: h.rank)
    assert top.confidence.value == "high"
    assert "4821" in top.summary or "pool" in top.summary.lower()


async def test_downstream_dependency_does_not_blame_own_deploy():
    result = await _run_scenario(
        "downstream-dependency",
        title="P99 latency SLO breach: checkout-api",
        service="checkout-api",
        severity=Severity.high,
        message="checkout-api p99 latency at 4.8s (SLO: 800ms).",
        stack_trace="TimeoutError: request to shipping-rates-api timed out after 4000ms",
    )
    assert result.status == InvestigationStatus.complete
    assert result.hypotheses
    top = min(result.hypotheses, key=lambda h: h.rank)
    assert "shipping-rates-api" in top.summary or "shipping-rates-api" in top.reasoning
    assert "2210" not in top.summary


async def test_ask_follow_up_resumes_session_and_cites_real_evidence():
    result = await _run_scenario(
        "bad-deploy",
        title="High error rate: payments-api",
        service="payments-api",
        severity=Severity.critical,
        message="5xx error rate for payments-api exceeded 8% threshold.",
        stack_trace="sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 0 reached",
    )
    assert result.status == InvestigationStatus.complete

    answer = await ask_follow_up(result, "Which PR number caused this, and who authored it?")
    assert "4821" in answer["answer"]
    assert answer["cited_evidence_ids"]
    real_ids = {e.id for e in result.evidence}
    assert all(eid in real_ids for eid in answer["cited_evidence_ids"])
