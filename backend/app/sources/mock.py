"""Mock implementations of `GitHubSource` and `ObservabilitySource`, backed by a
`Scenario` fixture. Both classes materialize the scenario's timedelta offsets
against a single `reference_time` (the alert's `fired_at`) so every demo run
looks like it just happened, and both apply real since/until window filtering —
the agent has to pick a wide-enough window to find things like the resource-leak
scenario's day-old root cause, exactly as it would against a real API.
"""
from __future__ import annotations

from datetime import datetime

from app.fixtures.scenarios.spec import MetricSeriesFixture, Scenario
from app.sources.base import (
    CodeOwner,
    Commit,
    Deploy,
    ErrorGroup,
    LogEntry,
    MetricPoint,
    MetricSeries,
    PullRequest,
    ServiceEdge,
)


class MockGitHubSource:
    def __init__(self, scenario: Scenario, reference_time: datetime) -> None:
        self._scenario = scenario
        self._now = reference_time

    def _is_tracked_service(self, service: str) -> bool:
        """Our tiny fixture world only has code/deploy history for the alert's own
        service. Without this guard, querying GitHub data for a dependency found via
        the service map (exactly what the dependency playbook tells the agent to do)
        would silently return the alert service's own commits/PRs/deploys relabeled
        under the wrong service name — confusing, and a real correctness bug, not
        just a cosmetic one."""
        return service == self._scenario.alert.service

    def list_recent_commits(self, service: str, since: datetime, until: datetime) -> list[Commit]:
        if not self._is_tracked_service(service):
            return []
        return [
            Commit(
                sha=c.sha,
                message=c.message,
                author=c.author,
                authored_at=self._now + c.offset,
                files_changed=c.files_changed,
                url=f"https://github.com/example/{service}/commit/{c.sha}",
            )
            for c in self._scenario.commits
            if since <= self._now + c.offset <= until
        ]

    def list_merged_prs(
        self, service: str, since: datetime, until: datetime
    ) -> list[PullRequest]:
        if not self._is_tracked_service(service):
            return []
        return [
            PullRequest(
                number=p.number,
                title=p.title,
                author=p.author,
                merged_at=self._now + p.merged_offset,
                files_changed=p.files_changed,
                additions=p.additions,
                deletions=p.deletions,
                diff_summary=p.diff_summary,
                url=f"https://github.com/example/{service}/pull/{p.number}",
                labels=p.labels,
            )
            for p in self._scenario.pull_requests
            if since <= self._now + p.merged_offset <= until
        ]

    def get_deploys(self, service: str, since: datetime, until: datetime) -> list[Deploy]:
        if not self._is_tracked_service(service):
            return []
        return [
            Deploy(
                id=d.id,
                service=service,
                version=d.version,
                deployed_at=self._now + d.offset,
                commit_sha=self._commit_sha(d.commit_key),
                pr_number=d.pr_number,
                status=d.status,
                url=f"https://github.com/example/{service}/deployments/{d.id}",
            )
            for d in self._scenario.deploys
            if since <= self._now + d.offset <= until
        ]

    def get_file_history(self, path: str, limit: int = 10) -> list[Commit]:
        matches = [
            Commit(
                sha=c.sha,
                message=c.message,
                author=c.author,
                authored_at=self._now + c.offset,
                files_changed=c.files_changed,
                url=f"https://github.com/example/repo/commit/{c.sha}",
            )
            for c in self._scenario.commits
            if any(path in f or f in path for f in c.files_changed)
        ]
        return sorted(matches, key=lambda c: c.authored_at, reverse=True)[:limit]

    def get_code_owners(self, service: str) -> list[CodeOwner]:
        if not self._is_tracked_service(service):
            return []
        return [
            CodeOwner(path_pattern=o.path_pattern, owners=o.owners)
            for o in self._scenario.code_owners
        ]

    def get_pr_diff(self, pr_number: int) -> str:
        for p in self._scenario.pull_requests:
            if p.number == pr_number:
                return p.diff_summary
        return f"No diff found for PR #{pr_number}"

    def _commit_sha(self, commit_key: str | None) -> str:
        if commit_key is None:
            return ""
        for c in self._scenario.commits:
            if c.key == commit_key:
                return c.sha
        return ""


class MockObservabilitySource:
    def __init__(self, scenario: Scenario, reference_time: datetime) -> None:
        self._scenario = scenario
        self._now = reference_time

    def _is_tracked_service(self, service: str) -> bool:
        """See MockGitHubSource._is_tracked_service — logs and error groups in our
        fixtures aren't service-namespaced, so querying a service we don't track
        would otherwise relabel the alert service's own logs under the wrong name."""
        return service == self._scenario.alert.service

    def _metric_service(self, m: MetricSeriesFixture) -> str:
        return m.service or self._scenario.alert.service

    def query_metric(
        self, service: str, metric_name: str, since: datetime, until: datetime
    ) -> MetricSeries:
        for m in self._scenario.metrics:
            if m.name == metric_name and self._metric_service(m) == service:
                points = [
                    MetricPoint(timestamp=self._now + offset, value=value)
                    for offset, value in m.points
                    if since <= self._now + offset <= until
                ]
                return MetricSeries(
                    name=m.name,
                    unit=m.unit,
                    service=service,
                    points=points,
                    baseline_value=m.baseline_value,
                )
        return MetricSeries(
            name=metric_name, unit="", service=service, points=[], baseline_value=0.0
        )

    def search_logs(
        self, service: str, query: str, since: datetime, until: datetime, limit: int = 50
    ) -> list[LogEntry]:
        if not self._is_tracked_service(service):
            return []
        query_lower = query.lower().strip()
        results = [
            LogEntry(
                timestamp=self._now + entry.offset,
                level=entry.level,
                service=service,
                message=entry.message,
                trace_id=entry.trace_id,
            )
            for entry in self._scenario.logs
            if since <= self._now + entry.offset <= until
            and (not query_lower or query_lower in entry.message.lower())
        ]
        return sorted(results, key=lambda e: e.timestamp)[:limit]

    def get_service_map(self, service: str) -> list[ServiceEdge]:
        return [
            ServiceEdge(from_service=e.from_service, to_service=e.to_service, call_kind=e.call_kind)
            for e in self._scenario.service_map
            if e.from_service == service or e.to_service == service
        ]

    def get_error_groups(
        self, service: str, since: datetime, until: datetime
    ) -> list[ErrorGroup]:
        if not self._is_tracked_service(service):
            return []
        return [
            ErrorGroup(
                fingerprint=g.fingerprint,
                title=g.title,
                service=service,
                count=g.count,
                first_seen=self._now + g.first_seen_offset,
                last_seen=self._now + g.last_seen_offset,
                sample_stack_trace=g.sample_stack_trace,
            )
            for g in self._scenario.error_groups
            if since <= self._now + g.last_seen_offset <= until
        ]

    def compare_baseline(self, service: str, metric_name: str, at: datetime) -> dict[str, float]:
        for m in self._scenario.metrics:
            if m.name == metric_name and self._metric_service(m) == service:
                closest = min(m.points, key=lambda p: abs((self._now + p[0]) - at))
                current = closest[1]
                baseline = m.baseline_value
                pct_change = ((current - baseline) / baseline * 100) if baseline else 0.0
                return {
                    "current": current,
                    "baseline": baseline,
                    "pct_change": round(pct_change, 1),
                }
        return {"current": 0.0, "baseline": 0.0, "pct_change": 0.0}


def build_mock_sources(
    scenario: Scenario, reference_time: datetime
) -> tuple[MockGitHubSource, MockObservabilitySource]:
    return (
        MockGitHubSource(scenario, reference_time),
        MockObservabilitySource(scenario, reference_time),
    )
