"""Live ObservabilitySource (PLAN.md Phase 7b), backed by the docker-compose stack
in observability-stack/: Prometheus (metrics), Loki (logs), GlitchTip (error
groups — a lightweight, Sentry-API-compatible stand-in for self-hosted Sentry;
see that directory's docker-compose.yml for why). `get_service_map` is a small
manually-maintained config, not derived — Prometheus has no native topology
concept, and a hand-maintained map is defensible since topology changes far less
often than the metrics/logs/errors that actually explain an incident.

Satisfies the same `ObservabilitySource` Protocol as `MockObservabilitySource`
(app/sources/base.py) — nothing above the source layer needs to know which one
it's talking to. Selected via `DATA_SOURCE=live` (app/config.py).

Deliberately synchronous (`httpx.Client`, not `AsyncClient`), matching the
Protocol exactly: the code that actually calls these methods
(`mcp_server/server.py`'s tool functions) runs in a separate subprocess spawned
by the `claude` CLI over stdio, not inside the FastAPI backend's own event
loop — a blocking HTTP call here doesn't block anything else, so there's no
async-refactor benefit to chase, only Protocol-shape risk to introduce.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

from app.sources.base import ErrorGroup, LogEntry, MetricPoint, MetricSeries, ServiceEdge

logger = logging.getLogger(__name__)

# One real service in this demo stack; a real multi-service deployment would look
# this up from the same kind of config `get_service_map` reads from.
_METRIC_QUERIES: dict[str, str] = {
    "error_rate": (
        '100 * (sum(rate(http_requests_total{status="500"}[1m])) or vector(0)) '
        "/ (sum(rate(http_requests_total[1m])) or vector(1))"
    ),
    "db_pool_in_use": "db_pool_in_use",
    "db_pool_size_configured": "db_pool_size_configured",
}

_METRIC_UNITS: dict[str, str] = {
    "error_rate": "pct",
    "db_pool_in_use": "connections",
    "db_pool_size_configured": "connections",
}

# Manually-maintained, per PLAN.md Phase 7b — not derived from any live topology API.
_SERVICE_MAP: list[ServiceEdge] = [
    ServiceEdge(from_service="payments-api", to_service="postgres-primary", call_kind="db"),
]


class LiveObservabilitySource:
    def __init__(
        self,
        *,
        prometheus_url: str,
        loki_url: str,
        glitchtip_url: str | None = None,
        glitchtip_api_token: str | None = None,
        glitchtip_org_slug: str | None = None,
        glitchtip_project_slug: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """`transport` is test-only: inject an `httpx.MockTransport` to test
        against recorded responses instead of the real network (see
        tests/test_observability_live.py) — never set in production use."""
        self._prometheus_url = prometheus_url.rstrip("/")
        self._loki_url = loki_url.rstrip("/")
        self._glitchtip_url = glitchtip_url.rstrip("/") if glitchtip_url else None
        self._glitchtip_api_token = glitchtip_api_token
        self._glitchtip_org_slug = glitchtip_org_slug
        self._transport = transport
        self._glitchtip_project_slug = glitchtip_project_slug

    def query_metric(
        self, service: str, metric_name: str, since: datetime, until: datetime
    ) -> MetricSeries:
        promql = _METRIC_QUERIES.get(metric_name)
        if promql is None:
            logger.warning("Unknown metric name %r for live Prometheus source", metric_name)
            return MetricSeries(
                name=metric_name, unit="", service=service, points=[], baseline_value=0.0
            )

        step = max(int((until - since).total_seconds() / 120), 5)
        with httpx.Client(timeout=10.0, transport=self._transport) as client:
            resp = client.get(
                f"{self._prometheus_url}/api/v1/query_range",
                params={
                    "query": promql,
                    "start": since.timestamp(),
                    "end": until.timestamp(),
                    "step": f"{step}s",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        points: list[MetricPoint] = []
        for result in data.get("data", {}).get("result", []):
            for ts, value in result.get("values", []):
                points.append(
                    MetricPoint(
                        timestamp=datetime.fromtimestamp(float(ts), tz=until.tzinfo),
                        value=float(value),
                    )
                )
        points.sort(key=lambda p: p.timestamp)

        return MetricSeries(
            name=metric_name,
            unit=_METRIC_UNITS.get(metric_name, ""),
            service=service,
            points=points,
            baseline_value=_baseline_from_points(points),
        )

    def compare_baseline(self, service: str, metric_name: str, at: datetime) -> dict[str, float]:
        series = self.query_metric(service, metric_name, at - timedelta(minutes=30), at)
        if not series.points:
            return {"current": 0.0, "baseline": 0.0, "pct_change": 0.0}
        current = series.points[-1].value
        baseline = series.baseline_value
        pct_change = ((current - baseline) / baseline * 100) if baseline else 0.0
        return {"current": current, "baseline": baseline, "pct_change": round(pct_change, 1)}

    def search_logs(
        self, service: str, query: str, since: datetime, until: datetime, limit: int = 50
    ) -> list[LogEntry]:
        logql = f'{{service="{service}"}}' + (f' |= "{query}"' if query else "")
        with httpx.Client(timeout=10.0, transport=self._transport) as client:
            resp = client.get(
                f"{self._loki_url}/loki/api/v1/query_range",
                params={
                    "query": logql,
                    "start": int(since.timestamp() * 1e9),
                    "end": int(until.timestamp() * 1e9),
                    "limit": limit,
                    "direction": "forward",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        entries: list[LogEntry] = []
        for stream in data.get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            for ts_ns, line in stream.get("values", []):
                entries.append(
                    LogEntry(
                        timestamp=datetime.fromtimestamp(int(ts_ns) / 1e9, tz=until.tzinfo),
                        level=_extract_level(line),
                        service=labels.get("service", service),
                        message=line,
                    )
                )
        entries.sort(key=lambda e: e.timestamp)
        return entries[:limit]

    def get_service_map(self, service: str) -> list[ServiceEdge]:
        return [e for e in _SERVICE_MAP if e.from_service == service or e.to_service == service]

    def get_error_groups(self, service: str, since: datetime, until: datetime) -> list[ErrorGroup]:
        if not (self._glitchtip_url and self._glitchtip_api_token and self._glitchtip_org_slug):
            logger.warning("GlitchTip not configured; live get_error_groups returning empty")
            return []

        with httpx.Client(timeout=10.0, transport=self._transport) as client:
            resp = client.get(
                f"{self._glitchtip_url}/api/0/projects/{self._glitchtip_org_slug}/"
                f"{self._glitchtip_project_slug}/issues/",
                headers={"Authorization": f"Bearer {self._glitchtip_api_token}"},
                params={"query": "is:unresolved"},
            )
            resp.raise_for_status()
            issues = resp.json()

        groups: list[ErrorGroup] = []
        for issue in issues:
            last_seen = _parse_iso(issue.get("lastSeen"))
            first_seen = _parse_iso(issue.get("firstSeen"))
            if last_seen and not (since <= last_seen <= until):
                continue
            groups.append(
                ErrorGroup(
                    fingerprint=str(issue.get("id", "")),
                    title=issue.get("title", ""),
                    service=service,
                    count=int(issue.get("count", 0)),
                    first_seen=first_seen or since,
                    last_seen=last_seen or until,
                    sample_stack_trace=issue.get("metadata", {}).get(
                        "value", issue.get("culprit", "")
                    ),
                )
            )
        return groups


def _baseline_from_points(points: list[MetricPoint]) -> float:
    """Adaptive, since this demo stack has no long-lived history to define a fixed
    baseline against: everything but the most recent 2 minutes is "baseline", used
    the same way compare_baseline splits current-vs-baseline explicitly."""
    if not points:
        return 0.0
    cutoff = points[-1].timestamp
    earlier = [p.value for p in points if (cutoff - p.timestamp).total_seconds() > 120]
    pool = earlier or [p.value for p in points]
    return round(sum(pool) / len(pool), 3)


def _extract_level(line: str) -> str:
    lower = line.lower()
    if '"level": "error"' in lower or '"level":"error"' in lower:
        return "error"
    if '"level": "warn"' in lower or '"level":"warn"' in lower:
        return "warn"
    return "info"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
