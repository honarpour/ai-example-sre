"""Scenario 3: slow resource leak.

report-worker's memory climbs gradually over ~20 hours until it hits the
container limit and starts OOM-killing pods. The actual culprit — an
in-process cache added without an eviction policy — merged yesterday, well
outside a naive "what changed in the last 30 minutes" window. The decoy is a
real, recent hotfix deploy (10 minutes before the alert, for an unrelated bug)
that a lazy "blame the latest deploy" agent would seize on. Correctly solving
this requires widening the investigation window based on the metric's own
shape (a slow ramp, not a step function) rather than trusting alert recency.
"""
from __future__ import annotations

from datetime import timedelta

from app.fixtures.scenarios.spec import (
    AlertTemplate,
    CodeOwnerFixture,
    CommitFixture,
    DeployFixture,
    ErrorGroupFixture,
    LogFixture,
    MetricSeriesFixture,
    PullRequestFixture,
    Scenario,
    ServiceEdgeFixture,
)

SERVICE = "report-worker"

SCENARIO = Scenario(
    key="resource-leak",
    name="Slow memory leak — unbounded cache",
    description="report-worker OOMKills after a gradual memory climb from a cache added yesterday.",
    alert=AlertTemplate(
        title="OOMKilled: report-worker",
        service=SERVICE,
        severity="critical",
        message=(
            "report-worker pods have been OOMKilled 6 times in the last 15 minutes. Memory usage "
            "reached 100% of the 2Gi limit before each kill."
        ),
        stack_trace=(
            "container report-worker-7d4f9 killed (OOMKilled): "
            "memory usage 2048Mi / 2048Mi limit"
        ),
    ),
    commits=[
        CommitFixture(
            key="unbounded-cache",
            sha="f00d1e2",
            message="Cache rendered report templates in-process to cut render latency",
            author="lsingh",
            offset=timedelta(hours=-21),
            files_changed=["app/rendering/template_cache.py"],
            is_correlated=True,
        ),
        CommitFixture(
            key="hotfix-commit",
            sha="9a8b7c6",
            message="Fix off-by-one in report pagination",
            author="dortiz",
            offset=timedelta(minutes=-11),
            files_changed=["app/reports/paginator.py"],
        ),
    ],
    pull_requests=[
        PullRequestFixture(
            key="unbounded-cache-pr",
            number=1187,
            title="Cache rendered report templates in-process to cut render latency",
            author="lsingh",
            merged_offset=timedelta(hours=-21),
            files_changed=["app/rendering/template_cache.py"],
            additions=58,
            deletions=3,
            diff_summary=(
                "Adds a module-level dict cache keyed by report_id -> rendered_bytes. "
                "No max size, no TTL, no eviction — every unique report rendered is retained "
                "for the process lifetime."
            ),
            labels=["performance"],
            is_correlated=True,
        ),
        PullRequestFixture(
            key="hotfix-pr",
            number=1201,
            title="Fix off-by-one in report pagination",
            author="dortiz",
            merged_offset=timedelta(minutes=-10),
            files_changed=["app/reports/paginator.py"],
            additions=3,
            deletions=1,
            diff_summary="One-line boundary fix in pagination loop, no allocation change.",
            labels=["bugfix"],
        ),
    ],
    deploys=[
        DeployFixture(
            key="unbounded-cache-deploy",
            id="dep-3301",
            version="v5.9.0",
            offset=timedelta(hours=-21),
            commit_key="unbounded-cache",
            pr_number=1187,
            is_correlated=True,
        ),
        DeployFixture(
            key="hotfix-deploy",
            id="dep-3340",
            version="v5.9.4",
            offset=timedelta(minutes=-9),
            commit_key="hotfix-commit",
            pr_number=1201,
        ),
    ],
    code_owners=[
        CodeOwnerFixture(path_pattern="app/rendering/*", owners=["@reports-team"]),
        CodeOwnerFixture(path_pattern="app/reports/*", owners=["@reports-team"]),
    ],
    logs=[
        LogFixture(
            key="oom-kill-1",
            offset=timedelta(minutes=-14),
            level="error",
            message="container report-worker-7d4f9 killed (OOMKilled): memory usage 2048Mi/2048Mi",
            is_correlated=True,
        ),
        LogFixture(
            key="oom-kill-2",
            offset=timedelta(minutes=-3),
            level="error",
            message="container report-worker-a91c2 killed (OOMKilled): memory usage 2048Mi/2048Mi",
            is_correlated=True,
        ),
        LogFixture(
            key="cache-size-warn",
            offset=timedelta(hours=-2),
            level="warn",
            message="template_cache size=48213 entries, approx 1.6GB resident",
            is_correlated=True,
        ),
        LogFixture(
            key="pagination-deployed",
            offset=timedelta(minutes=-9),
            level="info",
            message="deployed v5.9.4",
        ),
    ],
    metrics=[
        MetricSeriesFixture(
            name="memory_used_pct",
            unit="pct",
            baseline_value=22.0,
            points=[
                (timedelta(hours=-21), 21.0),
                (timedelta(hours=-18), 34.0),
                (timedelta(hours=-15), 48.0),
                (timedelta(hours=-12), 58.0),
                (timedelta(hours=-9), 67.0),
                (timedelta(hours=-6), 76.0),
                (timedelta(hours=-3), 85.0),
                (timedelta(hours=-1), 93.0),
                (timedelta(minutes=-20), 97.0),
                (timedelta(minutes=-14), 100.0),
                (timedelta(minutes=-9), 88.0),  # dips after each OOMKill restart, then climbs again
                (timedelta(minutes=-3), 100.0),
                (timedelta(minutes=0), 91.0),
            ],
        ),
        MetricSeriesFixture(
            name="oom_kill_count",
            unit="count",
            baseline_value=0.0,
            points=[
                (timedelta(minutes=-14), 1.0),
                (timedelta(minutes=-11), 2.0),
                (timedelta(minutes=-9), 3.0),
                (timedelta(minutes=-6), 4.0),
                (timedelta(minutes=-3), 5.0),
                (timedelta(minutes=0), 6.0),
            ],
        ),
    ],
    error_groups=[
        ErrorGroupFixture(
            key="oom-kill-group",
            fingerprint="OOMKilled@report-worker",
            title="Pod OOMKilled",
            first_seen_offset=timedelta(minutes=-14),
            last_seen_offset=timedelta(minutes=-3),
            count=6,
            sample_stack_trace=(
                "container report-worker killed (OOMKilled): memory usage 2048Mi/2048Mi"
            ),
            is_correlated=True,
        ),
    ],
    service_map=[
        ServiceEdgeFixture(from_service="job-scheduler", to_service=SERVICE, call_kind="queue"),
        ServiceEdgeFixture(from_service=SERVICE, to_service="s3-reports", call_kind="http"),
    ],
    expected_root_cause=(
        "PR #1187 (merged ~21 hours before the alert) added an in-process template cache with no "
        "eviction policy. Memory grew steadily over the following 21 hours (see memory_used_pct "
        "ramp, and the cache-size warning log) until pods began OOMKilling. The hotfix deployed 9 "
        "minutes before the alert (PR #1201) is unrelated — a one-line pagination fix with no "
        "allocation impact — and is a decoy for 'blame the latest deploy.'"
    ),
    expected_correlated_keys=[
        "unbounded-cache",
        "unbounded-cache-pr",
        "unbounded-cache-deploy",
        "oom-kill-1",
        "oom-kill-2",
        "cache-size-warn",
        "oom-kill-group",
    ],
)
