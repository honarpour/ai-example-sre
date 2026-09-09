"""Scenario 1: bad deploy.

A PR shrinks a DB connection pool size "to save memory," merges, and deploys.
Six minutes later the error rate spikes as the pool saturates under normal
load. This is the "obvious" case — the agent should nail it quickly and with
high confidence — but it still includes a decoy (an unrelated deploy to a
different service in the same window, plus a noisy irrelevant log cluster) so
"most recent deploy" pattern-matching isn't enough on its own to look correct;
the agent has to show the file-path/stack-trace correlation, not just timing.
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

SERVICE = "payments-api"

SCENARIO = Scenario(
    key="bad-deploy",
    name="Bad deploy — connection pool exhaustion",
    description="Error rate spike in payments-api minutes after a config-shrinking deploy.",
    alert=AlertTemplate(
        title="High error rate: payments-api",
        service=SERVICE,
        severity="critical",
        message=(
            "5xx error rate for payments-api exceeded 8% (threshold 2%) over the last 5 minutes. "
            "Currently sustained at 11.4%."
        ),
        stack_trace=(
            "sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 0 reached, "
            "connection timed out, timeout 30\n"
            '  File "app/db/session.py", line 42, in get_connection\n'
            '  File "app/services/charge_service.py", line 118, in create_charge\n'
            '  File "app/routes/charges.py", line 33, in post_charge'
        ),
    ),
    commits=[
        CommitFixture(
            key="pool-shrink",
            sha="a1b2c3d",
            message="Reduce DB pool size to cut idle connection cost",
            author="jchen",
            offset=timedelta(minutes=-9),
            files_changed=["app/db/session.py", "config/database.yaml"],
            is_correlated=True,
        ),
        CommitFixture(
            key="unrelated-lint",
            sha="e4f5a6b",
            message="Fix lint warnings in notifications module",
            author="rpatel",
            offset=timedelta(minutes=-40),
            files_changed=["app/services/notification_service.py"],
        ),
    ],
    pull_requests=[
        PullRequestFixture(
            key="pool-shrink-pr",
            number=4821,
            title="Reduce DB pool size to cut idle connection cost",
            author="jchen",
            merged_offset=timedelta(minutes=-8),
            files_changed=["app/db/session.py", "config/database.yaml"],
            additions=4,
            deletions=4,
            diff_summary=(
                "config/database.yaml: pool_size: 20 -> 5, max_overflow: 10 -> 0\n"
                "app/db/session.py: read pool_size/max_overflow from config instead of hardcoded"
            ),
            labels=["infra", "cost-savings"],
            is_correlated=True,
        ),
        PullRequestFixture(
            key="unrelated-lint-pr",
            number=4815,
            title="Fix lint warnings in notifications module",
            author="rpatel",
            merged_offset=timedelta(minutes=-39),
            files_changed=["app/services/notification_service.py"],
            additions=12,
            deletions=9,
            diff_summary="Whitespace and unused-import cleanup, no behavior change.",
            labels=["chore"],
        ),
    ],
    deploys=[
        DeployFixture(
            key="pool-shrink-deploy",
            id="dep-9931",
            version="v2.44.0",
            offset=timedelta(minutes=-6),
            commit_key="pool-shrink",
            pr_number=4821,
            is_correlated=True,
        ),
        DeployFixture(
            key="unrelated-deploy",
            id="dep-9928",
            version="v1.12.3",
            offset=timedelta(minutes=-25),
            commit_key="unrelated-lint",
            pr_number=4815,
        ),
    ],
    code_owners=[
        CodeOwnerFixture(path_pattern="app/db/*", owners=["@jchen", "@platform-team"]),
        CodeOwnerFixture(path_pattern="app/services/*", owners=["@payments-team"]),
    ],
    logs=[
        LogFixture(
            key="pool-timeout-1",
            offset=timedelta(minutes=-4, seconds=-30),
            level="error",
            message="QueuePool limit of size 5 overflow 0 reached, connection timed out",
            trace_id="trc-88a1",
            is_correlated=True,
        ),
        LogFixture(
            key="pool-timeout-2",
            offset=timedelta(minutes=-2),
            level="error",
            message="QueuePool limit of size 5 overflow 0 reached, connection timed out",
            trace_id="trc-88c4",
            is_correlated=True,
        ),
        LogFixture(
            key="noisy-deprecation",
            offset=timedelta(minutes=-15),
            level="warn",
            message="DeprecationWarning: notification_service.send_legacy() will be removed in v3",
        ),
        LogFixture(
            key="noisy-deprecation-2",
            offset=timedelta(minutes=-10),
            level="warn",
            message="DeprecationWarning: notification_service.send_legacy() will be removed in v3",
        ),
    ],
    metrics=[
        MetricSeriesFixture(
            name="error_rate",
            unit="pct",
            baseline_value=0.8,
            points=[
                (timedelta(minutes=-30), 0.7),
                (timedelta(minutes=-20), 0.9),
                (timedelta(minutes=-10), 0.8),
                (timedelta(minutes=-6), 1.1),
                (timedelta(minutes=-5), 3.4),
                (timedelta(minutes=-4), 7.8),
                (timedelta(minutes=-3), 9.6),
                (timedelta(minutes=-2), 10.9),
                (timedelta(minutes=-1), 11.2),
                (timedelta(minutes=0), 11.4),
            ],
        ),
        MetricSeriesFixture(
            name="db_pool_in_use",
            unit="connections",
            baseline_value=3.0,
            points=[
                (timedelta(minutes=-10), 3.1),
                (timedelta(minutes=-6), 4.8),
                (timedelta(minutes=-5), 5.0),
                (timedelta(minutes=-4), 5.0),
                (timedelta(minutes=-2), 5.0),
                (timedelta(minutes=0), 5.0),
            ],
        ),
    ],
    error_groups=[
        ErrorGroupFixture(
            key="pool-timeout-group",
            fingerprint="sqlalchemy.exc.TimeoutError@charge_service.py:118",
            title="TimeoutError: QueuePool limit reached",
            first_seen_offset=timedelta(minutes=-5),
            last_seen_offset=timedelta(seconds=-10),
            count=214,
            sample_stack_trace=(
                "sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 0 reached\n"
                '  File "app/db/session.py", line 42, in get_connection\n'
                '  File "app/services/charge_service.py", line 118, in create_charge'
            ),
            is_correlated=True,
        ),
    ],
    service_map=[
        ServiceEdgeFixture(from_service="checkout-api", to_service=SERVICE, call_kind="http"),
        ServiceEdgeFixture(from_service=SERVICE, to_service="postgres-primary", call_kind="db"),
    ],
    expected_root_cause=(
        "PR #4821 dropped the DB connection pool size from 20 to 5 (and max_overflow from 10 to "
        "0) to cut idle connection cost. Deployed 6 minutes before the alert, it exhausted the "
        "pool under normal load, causing SQLAlchemy TimeoutErrors and the 5xx spike."
    ),
    expected_correlated_keys=[
        "pool-shrink",
        "pool-shrink-pr",
        "pool-shrink-deploy",
        "pool-timeout-1",
        "pool-timeout-2",
        "pool-timeout-group",
    ],
)
