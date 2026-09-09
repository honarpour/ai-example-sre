"""Regression tests for `_apply_synthesis`'s defensive parsing, added after a
review pass found that a single malformed hypothesis/action from the model
(unknown `kind`, missing required field) would raise and discard an entire
completed, already-paid-for investigation instead of just dropping that item."""
from __future__ import annotations

from datetime import UTC, datetime

from app.models.domain import Alert, AlertSource, Investigation, Severity
from app.orchestrator.runner import _apply_synthesis


def _investigation() -> Investigation:
    alert = Alert(
        title="t", service="s", severity=Severity.high, message="m",
        fired_at=datetime.now(UTC), source=AlertSource.manual, scenario="bad-deploy",
    )
    return Investigation(alert=alert, created_at=datetime.now(UTC))


def test_unknown_action_kind_is_dropped_not_fatal():
    inv = _investigation()
    structured = {
        "tldr": "summary",
        "hypotheses": [
            {
                "summary": "s",
                "reasoning": "r",
                "confidence": "high",
                "evidence_ids": [],
                "suggested_actions": [
                    {"kind": "not-a-real-kind", "title": "x", "description": "y"},
                    {"kind": "verification", "title": "good one", "description": "y"},
                ],
            }
        ],
    }
    _apply_synthesis(inv, structured, {})
    assert len(inv.hypotheses) == 1
    assert len(inv.hypotheses[0].suggested_actions) == 1
    assert inv.hypotheses[0].suggested_actions[0].title == "good one"


def test_missing_action_field_is_dropped_not_fatal():
    inv = _investigation()
    structured = {
        "tldr": "summary",
        "hypotheses": [
            {
                "summary": "s",
                "reasoning": "r",
                "confidence": "high",
                "evidence_ids": [],
                "suggested_actions": [{"kind": "verification", "title": "missing description"}],
            }
        ],
    }
    _apply_synthesis(inv, structured, {})
    assert inv.hypotheses[0].suggested_actions == []


def test_unknown_confidence_value_falls_back_to_low():
    inv = _investigation()
    structured = {
        "tldr": "summary",
        "hypotheses": [
            {"summary": "s", "reasoning": "r", "confidence": "extremely-sure", "evidence_ids": []}
        ],
    }
    _apply_synthesis(inv, structured, {})
    assert inv.hypotheses[0].confidence.value == "low"
