"""Tests for LiveObservabilitySource against recorded/synthetic HTTP responses
(httpx.MockTransport) — no real network, no running stack required. Response
shapes are trimmed real payloads captured against the actual observability-stack
services (Prometheus, Loki, GlitchTip) while building Phase 7b, not guessed."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from app.sources.observability_live import LiveObservabilitySource

NOW = datetime(2026, 8, 30, 2, 0, 0, tzinfo=UTC)


def _source(handler) -> LiveObservabilitySource:
    return LiveObservabilitySource(
        prometheus_url="http://prometheus.test",
        loki_url="http://loki.test",
        glitchtip_url="http://glitchtip.test",
        glitchtip_api_token="test-token",
        glitchtip_org_slug="sre-demo",
        glitchtip_project_slug="payments-api",
        transport=httpx.MockTransport(handler),
    )


def test_query_metric_parses_prometheus_range_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "query_range" in str(request.url)
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [
                        {
                            "metric": {"service": "payments-api"},
                            "values": [
                                [1788051600, "0.7"],
                                [1788051660, "11.4"],
                            ],
                        }
                    ],
                },
            },
        )

    src = _source(handler)
    series = src.query_metric("payments-api", "error_rate", NOW, NOW)
    assert series.name == "error_rate"
    assert series.unit == "pct"
    assert len(series.points) == 2
    assert series.points[-1].value == 11.4


def test_query_metric_unknown_name_returns_empty_without_a_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not make a request for an unmapped metric name")

    src = _source(handler)
    series = src.query_metric("payments-api", "not_a_real_metric", NOW, NOW)
    assert series.points == []


def test_search_logs_parses_loki_streams_and_extracts_level():
    def handler(request: httpx.Request) -> httpx.Response:
        assert 'service="payments-api"' in str(request.url) or "query_range" in str(request.url)
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "streams",
                    "result": [
                        {
                            "stream": {"service": "payments-api"},
                            "values": [
                                [
                                    "1788051660000000000",
                                    json.dumps({"level": "error", "message": "boom"}),
                                ]
                            ],
                        }
                    ],
                },
            },
        )

    src = _source(handler)
    entries = src.search_logs("payments-api", "", NOW, NOW)
    assert len(entries) == 1
    assert entries[0].level == "error"
    assert entries[0].service == "payments-api"


def test_get_error_groups_filters_by_window_and_maps_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": 42,
                    "title": "QueuePool limit reached",
                    "count": 214,
                    "firstSeen": "2026-08-30T01:55:00Z",
                    "lastSeen": "2026-08-30T02:00:00Z",
                    "metadata": {"value": "TimeoutError"},
                },
                {
                    "id": 43,
                    "title": "Old, unrelated issue",
                    "count": 3,
                    "firstSeen": "2020-01-01T00:00:00Z",
                    "lastSeen": "2020-01-01T00:05:00Z",
                    "metadata": {"value": "AncientError"},
                },
            ],
        )

    src = _source(handler)
    from datetime import timedelta

    groups = src.get_error_groups("payments-api", NOW - timedelta(minutes=10), NOW)
    assert len(groups) == 1
    assert groups[0].fingerprint == "42"
    assert groups[0].count == 214
    assert groups[0].sample_stack_trace == "TimeoutError"


def test_get_error_groups_without_glitchtip_configured_returns_empty():
    src = LiveObservabilitySource(prometheus_url="http://x", loki_url="http://x")
    groups = src.get_error_groups("payments-api", NOW, NOW)
    assert groups == []


def test_get_service_map_is_static_config_not_a_network_call():
    src = LiveObservabilitySource(prometheus_url="http://x", loki_url="http://x")
    edges = src.get_service_map("payments-api")
    assert any(e.to_service == "postgres-primary" for e in edges)


def test_compare_baseline_computes_pct_change_from_series():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {
                            "metric": {},
                            "values": [
                                [1788051000, "1.0"],
                                [1788051060, "1.0"],
                                [1788051540, "10.0"],
                            ],
                        }
                    ]
                },
            },
        )

    src = _source(handler)
    result = src.compare_baseline("payments-api", "error_rate", NOW)
    assert result["current"] == 10.0
    assert result["baseline"] == 1.0
    assert result["pct_change"] == 900.0
