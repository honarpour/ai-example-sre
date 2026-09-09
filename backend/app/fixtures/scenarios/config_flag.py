"""Scenario 4: feature-flag flip, no deploy.

search-api's error rate spikes after an ops engineer flips the
`new_ranking_algorithm` flag to 100% rollout — no code was deployed. This
scenario proves the agent doesn't assume "no recent deploy" means "no
findable cause": it must search logs/audit-events for config or flag changes,
not just GitHub. Decoy: a merged-but-not-yet-deployed PR sitting in the
timeline (further evidence that deploys aren't the mechanism here).
"""
from __future__ import annotations

from datetime import timedelta

from app.fixtures.scenarios.spec import (
    AlertTemplate,
    CodeOwnerFixture,
    ErrorGroupFixture,
    LogFixture,
    MetricSeriesFixture,
    PullRequestFixture,
    Scenario,
    ServiceEdgeFixture,
)

SERVICE = "search-api"

SCENARIO = Scenario(
    key="config-flag",
    name="Feature flag flip — no deploy",
    description="search-api errors spike after a flag rollout, with no corresponding deploy.",
    alert=AlertTemplate(
        title="Elevated error rate: search-api",
        service=SERVICE,
        severity="high",
        message=(
            "search-api 5xx rate reached 6.2% (threshold 2%) over the last 8 minutes. No deploy "
            "detected in the last 2 hours."
        ),
        stack_trace=(
            "KeyError: 'embedding_v2' not found in feature store\n"
            '  File "app/ranking/new_ranking_algorithm.py", line 71, in score\n'
            '  File "app/routes/search.py", line 40, in get_results"'
        ),
    ),
    pull_requests=[
        PullRequestFixture(
            key="ranking-pr-not-deployed",
            number=3390,
            title="Add fallback for missing embedding_v2 in new ranking algorithm",
            author="twu",
            merged_offset=timedelta(minutes=-3),
            files_changed=["app/ranking/new_ranking_algorithm.py"],
            additions=14,
            deletions=2,
            diff_summary=(
                "Adds a fallback path when embedding_v2 is missing from the feature store. "
                "Merged but NOT yet deployed — next deploy window is in 40 minutes."
            ),
            labels=["bugfix", "ranking"],
        ),
    ],
    code_owners=[
        CodeOwnerFixture(path_pattern="app/ranking/*", owners=["@search-relevance-team"]),
    ],
    logs=[
        LogFixture(
            key="flag-flip-audit",
            offset=timedelta(minutes=-9),
            level="info",
            message=(
                "[audit] feature_flag 'new_ranking_algorithm' rollout changed 10% -> 100% by "
                "ops-console user=pgarcia"
            ),
            is_correlated=True,
        ),
        LogFixture(
            key="ranking-keyerror-1",
            offset=timedelta(minutes=-8),
            level="error",
            message="KeyError: 'embedding_v2' not found in feature store",
            trace_id="trc-f301",
            is_correlated=True,
        ),
        LogFixture(
            key="ranking-keyerror-2",
            offset=timedelta(minutes=-2),
            level="error",
            message="KeyError: 'embedding_v2' not found in feature store",
            trace_id="trc-f309",
            is_correlated=True,
        ),
        LogFixture(
            key="unrelated-cache-info",
            offset=timedelta(minutes=-25),
            level="info",
            message="query_cache hit_rate=0.87 over last 5m window",
        ),
    ],
    metrics=[
        MetricSeriesFixture(
            name="error_rate",
            unit="pct",
            baseline_value=0.5,
            points=[
                (timedelta(minutes=-20), 0.4),
                (timedelta(minutes=-10), 0.5),
                (timedelta(minutes=-9), 0.6),
                (timedelta(minutes=-8), 2.1),
                (timedelta(minutes=-6), 4.0),
                (timedelta(minutes=-4), 5.3),
                (timedelta(minutes=-2), 6.0),
                (timedelta(minutes=0), 6.2),
            ],
        ),
        MetricSeriesFixture(
            name="new_ranking_algorithm_rollout_pct",
            unit="pct",
            baseline_value=10.0,
            points=[
                (timedelta(minutes=-10), 10.0),
                (timedelta(minutes=-9), 100.0),
                (timedelta(minutes=0), 100.0),
            ],
        ),
    ],
    error_groups=[
        ErrorGroupFixture(
            key="ranking-keyerror-group",
            fingerprint="KeyError@new_ranking_algorithm.py:71",
            title="KeyError: embedding_v2 not found in feature store",
            first_seen_offset=timedelta(minutes=-8),
            last_seen_offset=timedelta(seconds=-10),
            count=189,
            sample_stack_trace=(
                "KeyError: 'embedding_v2' not found in feature store\n"
                '  File "app/ranking/new_ranking_algorithm.py", line 71, in score'
            ),
            is_correlated=True,
        ),
    ],
    service_map=[
        ServiceEdgeFixture(from_service="web-frontend", to_service=SERVICE, call_kind="http"),
        ServiceEdgeFixture(from_service=SERVICE, to_service="feature-store", call_kind="grpc"),
    ],
    expected_root_cause=(
        "No deploy occurred. An ops-console change rolled the 'new_ranking_algorithm' feature "
        "flag from 10% to 100% 9 minutes before the alert; the algorithm reads 'embedding_v2' "
        "from the feature store, which isn't populated for the newly-included 90% of traffic, "
        "causing KeyErrors. PR #3390 (a fallback fix) is merged but not yet deployed."
    ),
    expected_correlated_keys=[
        "flag-flip-audit",
        "ranking-keyerror-1",
        "ranking-keyerror-2",
        "ranking-keyerror-group",
    ],
    expects_no_code_change=True,
)
