"""Data source interfaces. GitHub and observability are each a `Protocol` — mock
and (Phase 7) live implementations satisfy the same shape, so the agent's tools
never know which one they're talking to.

Every method takes a `now` reference point (the alert's fired_at) so mock data can
be generated relative to it and always looks fresh in a demo, and every return
type is a plain dataclass the MCP layer serializes directly to a tool result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class Commit:
    sha: str
    message: str
    author: str
    authored_at: datetime
    files_changed: list[str]
    url: str


@dataclass
class PullRequest:
    number: int
    title: str
    author: str
    merged_at: datetime | None
    files_changed: list[str]
    additions: int
    deletions: int
    diff_summary: str
    """Short human-readable summary of the diff, not the full patch (keeps tool output small)."""
    url: str
    labels: list[str] = field(default_factory=list)


@dataclass
class Deploy:
    id: str
    service: str
    version: str
    deployed_at: datetime
    commit_sha: str
    pr_number: int | None
    status: str
    """'success' | 'failed' | 'rolled_back'"""
    url: str


@dataclass
class CodeOwner:
    path_pattern: str
    owners: list[str]


@dataclass
class LogEntry:
    timestamp: datetime
    level: str
    service: str
    message: str
    trace_id: str | None = None


@dataclass
class MetricPoint:
    timestamp: datetime
    value: float


@dataclass
class MetricSeries:
    name: str
    unit: str
    service: str
    points: list[MetricPoint]
    baseline_value: float
    """Typical/expected value, for the UI to render a baseline reference line."""


@dataclass
class ErrorGroup:
    fingerprint: str
    title: str
    service: str
    count: int
    first_seen: datetime
    last_seen: datetime
    sample_stack_trace: str


@dataclass
class ServiceEdge:
    from_service: str
    to_service: str
    call_kind: str
    """'http' | 'grpc' | 'db' | 'queue'"""


@runtime_checkable
class GitHubSource(Protocol):
    def list_recent_commits(
        self, service: str, since: datetime, until: datetime
    ) -> list[Commit]: ...

    def list_merged_prs(
        self, service: str, since: datetime, until: datetime
    ) -> list[PullRequest]: ...

    def get_deploys(self, service: str, since: datetime, until: datetime) -> list[Deploy]: ...

    def get_file_history(self, path: str, limit: int = 10) -> list[Commit]: ...

    def get_code_owners(self, service: str) -> list[CodeOwner]: ...

    def get_pr_diff(self, pr_number: int) -> str: ...


@runtime_checkable
class ObservabilitySource(Protocol):
    def query_metric(
        self, service: str, metric_name: str, since: datetime, until: datetime
    ) -> MetricSeries: ...

    def search_logs(
        self, service: str, query: str, since: datetime, until: datetime, limit: int = 50
    ) -> list[LogEntry]: ...

    def get_service_map(self, service: str) -> list[ServiceEdge]: ...

    def get_error_groups(
        self, service: str, since: datetime, until: datetime
    ) -> list[ErrorGroup]: ...

    def compare_baseline(
        self, service: str, metric_name: str, at: datetime
    ) -> dict[str, float]:
        """Returns {'current': float, 'baseline': float, 'pct_change': float}."""
        ...
