"""Fast, no-CLI tests for the HTTP layer. The background investigation task is
stubbed out — these tests are about the API contract (scenario presets vs raw
webhook payloads, validation, 404s), not the agent itself (see test_runner_live.py
for that)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.domain import (
    Alert,
    AlertSource,
    Confidence,
    Hypothesis,
    Investigation,
    Severity,
)
from app.store import store


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.api.routes.run_investigation", AsyncMock())
    return TestClient(app)


def _make_investigation_with_hypothesis() -> Investigation:
    alert = Alert(
        title="Test alert",
        service="test-service",
        severity=Severity.high,
        message="Something broke",
        fired_at=datetime.now(UTC),
        source=AlertSource.manual,
        scenario="bad-deploy",
    )
    investigation = Investigation(alert=alert, created_at=datetime.now(UTC))
    investigation.hypotheses.append(
        Hypothesis(
            rank=1,
            summary="Test hypothesis",
            reasoning="Because tests",
            confidence=Confidence.high,
            evidence_ids=[],
        )
    )
    store.create(investigation)
    return investigation


def test_create_alert_from_scenario_preset_fills_in_fields(client):
    resp = client.post("/api/alerts", json={"scenario": "bad-deploy"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["alert"]["service"] == "payments-api"
    assert body["alert"]["scenario"] == "bad-deploy"
    assert body["alert"]["title"]
    assert body["alert"]["message"]


def test_create_alert_from_scenario_preset_allows_overrides(client):
    resp = client.post(
        "/api/alerts", json={"scenario": "bad-deploy", "severity": "low"}
    )
    assert resp.status_code == 200
    assert resp.json()["alert"]["severity"] == "low"


def test_create_alert_unknown_scenario_404s(client):
    resp = client.post("/api/alerts", json={"scenario": "not-a-scenario"})
    assert resp.status_code == 404


def test_create_alert_raw_webhook_requires_fields(client):
    resp = client.post("/api/alerts", json={"title": "x"})
    assert resp.status_code == 422


def test_create_alert_raw_webhook_with_all_fields_succeeds(client):
    resp = client.post(
        "/api/alerts",
        json={
            "title": "Custom alert",
            "service": "custom-service",
            "severity": "high",
            "message": "Something broke",
            "source": "webhook",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["alert"]["scenario"] is None


def test_list_scenarios_returns_all_four(client):
    resp = client.get("/api/scenarios")
    assert resp.status_code == 200
    keys = {s["key"] for s in resp.json()}
    assert keys == {"bad-deploy", "downstream-dependency", "resource-leak", "config-flag"}


def test_get_unknown_investigation_404s(client):
    resp = client.get("/api/investigations/does-not-exist")
    assert resp.status_code == 404


def test_submit_feedback_succeeds_for_real_hypothesis(client):
    investigation = _make_investigation_with_hypothesis()
    hypothesis_id = investigation.hypotheses[0].id
    resp = client.post(
        f"/api/investigations/{investigation.id}/feedback",
        json={"hypothesis_id": hypothesis_id, "helpful": True},
    )
    assert resp.status_code == 200
    feedback = resp.json()["feedback"]
    assert len(feedback) == 1
    assert feedback[0]["hypothesis_id"] == hypothesis_id
    assert feedback[0]["helpful"] is True
    assert feedback[0]["created_at"]  # server-set, not client-supplied


def test_submit_feedback_unknown_hypothesis_404s(client):
    investigation = _make_investigation_with_hypothesis()
    resp = client.post(
        f"/api/investigations/{investigation.id}/feedback",
        json={"hypothesis_id": "not-a-real-id", "helpful": False},
    )
    assert resp.status_code == 404


def test_submit_feedback_unknown_investigation_404s(client):
    resp = client.post(
        "/api/investigations/does-not-exist/feedback",
        json={"hypothesis_id": "x", "helpful": True},
    )
    assert resp.status_code == 404


def test_ask_follow_up_without_session_returns_409(client):
    investigation = _make_investigation_with_hypothesis()
    resp = client.post(
        f"/api/investigations/{investigation.id}/ask",
        json={"question": "was this in the canary too?"},
    )
    assert resp.status_code == 409


def test_ask_follow_up_unknown_investigation_404s(client):
    resp = client.post(
        "/api/investigations/does-not-exist/ask",
        json={"question": "anything"},
    )
    assert resp.status_code == 404
