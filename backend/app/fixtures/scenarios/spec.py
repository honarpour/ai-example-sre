"""Scenario fixture spec.

A `Scenario` is a self-contained, hand-authored "world": an alert, and everything
a GitHub + observability source would return if asked about it. All timestamps
are stored as **offsets** (timedelta from the alert's `fired_at`) so the same
scenario can be replayed against any `fired_at` and still look like it just
happened — this is what keeps demos from ever looking stale.

Every scenario also carries `expected_root_cause` fields used by the eval
harness (Phase 5): the correlating evidence is tagged with a stable `key` so
the harness can check "did the agent's winning hypothesis cite the right
evidence" without string-matching prose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta


@dataclass
class CommitFixture:
    key: str
    sha: str
    message: str
    author: str
    offset: timedelta
    files_changed: list[str]
    is_correlated: bool = False
    """True if this is part of the actual root cause chain (vs. a decoy)."""


@dataclass
class PullRequestFixture:
    key: str
    number: int
    title: str
    author: str
    merged_offset: timedelta
    files_changed: list[str]
    additions: int
    deletions: int
    diff_summary: str
    labels: list[str] = field(default_factory=list)
    is_correlated: bool = False


@dataclass
class DeployFixture:
    key: str
    id: str
    version: str
    offset: timedelta
    commit_key: str
    pr_number: int | None
    status: str = "success"
    is_correlated: bool = False


@dataclass
class CodeOwnerFixture:
    path_pattern: str
    owners: list[str]


@dataclass
class LogFixture:
    key: str
    offset: timedelta
    level: str
    message: str
    trace_id: str | None = None
    is_correlated: bool = False


@dataclass
class MetricSeriesFixture:
    name: str
    unit: str
    baseline_value: float
    """(offset, value) points. The onset offset is where the metric visibly departs baseline."""
    points: list[tuple[timedelta, float]]
    service: str | None = None
    """Which service this metric belongs to. Defaults to the scenario's own alert.service —
    set explicitly for a metric that models a DIFFERENT service (e.g. a downstream
    dependency's own latency), so querying the wrong service can't return it relabeled."""


@dataclass
class ErrorGroupFixture:
    key: str
    fingerprint: str
    title: str
    first_seen_offset: timedelta
    last_seen_offset: timedelta
    count: int
    sample_stack_trace: str
    is_correlated: bool = False


@dataclass
class ServiceEdgeFixture:
    from_service: str
    to_service: str
    call_kind: str


@dataclass
class AlertTemplate:
    title: str
    service: str
    severity: str
    message: str
    stack_trace: str | None = None


@dataclass
class Scenario:
    key: str
    name: str
    description: str
    """One-line summary shown in the 'Create Alert' preset picker."""
    alert: AlertTemplate

    commits: list[CommitFixture] = field(default_factory=list)
    pull_requests: list[PullRequestFixture] = field(default_factory=list)
    deploys: list[DeployFixture] = field(default_factory=list)
    code_owners: list[CodeOwnerFixture] = field(default_factory=list)
    logs: list[LogFixture] = field(default_factory=list)
    metrics: list[MetricSeriesFixture] = field(default_factory=list)
    error_groups: list[ErrorGroupFixture] = field(default_factory=list)
    service_map: list[ServiceEdgeFixture] = field(default_factory=list)

    expected_root_cause: str = ""
    """Prose description used by the eval LLM-judge (Phase 5)."""
    expected_correlated_keys: list[str] = field(default_factory=list)
    """Keys of the fixture items (commits/PRs/deploys/logs/error_groups) that ARE the root
    cause, for deterministic evidence precision/recall scoring."""
    expects_no_code_change: bool = False
    """True for scenarios where the correct conclusion is 'not a deploy' — the agent should
    NOT confidently pin a hypothesis on any commit/PR/deploy."""
