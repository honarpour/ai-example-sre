"""Scenario 2: downstream dependency failure.

checkout-api's latency alert fires, but checkout-api itself has shipped nothing
unusual — the real cause is elevated latency in shipping-rates-api, a service
it calls synchronously. This is the highest-signal scenario in the whole demo:
the decoy is a real, recently-merged PR in checkout-api (a copy change behind a
feature flag) that is temporally close to the alert but causally irrelevant.
The correct hypothesis must point at the *dependency*, not checkout-api's own
recent activity, and the correct evidence set must explicitly exclude the
decoy PR/deploy.
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

SERVICE = "checkout-api"
UPSTREAM = "shipping-rates-api"

SCENARIO = Scenario(
    key="downstream-dependency",
    name="Downstream dependency degraded",
    description="checkout-api latency spikes from a slow upstream dependency, not its own code.",
    alert=AlertTemplate(
        title="P99 latency SLO breach: checkout-api",
        service=SERVICE,
        severity="high",
        message=(
            "checkout-api p99 latency at 4.8s (SLO: 800ms) for the /checkout/quote endpoint over "
            "the last 10 minutes."
        ),
        stack_trace=(
            "TimeoutError: request to shipping-rates-api timed out after 4000ms\n"
            '  File "app/clients/shipping_rates_client.py", line 55, in get_rates\n'
            '  File "app/services/quote_service.py", line 29, in build_quote\n'
            '  File "app/routes/checkout.py", line 61, in post_quote'
        ),
    ),
    commits=[
        CommitFixture(
            key="flag-copy-change",
            sha="c9d8e7f",
            message="Update promo banner copy behind holiday_promo flag",
            author="mkwon",
            offset=timedelta(minutes=-12),
            files_changed=["app/templates/promo_banner.html"],
        ),
    ],
    pull_requests=[
        PullRequestFixture(
            key="flag-copy-pr",
            number=2210,
            title="Update promo banner copy behind holiday_promo flag",
            author="mkwon",
            merged_offset=timedelta(minutes=-11),
            files_changed=["app/templates/promo_banner.html"],
            additions=6,
            deletions=6,
            diff_summary="Text-only copy change inside an existing feature-flagged banner.",
            labels=["marketing", "flagged"],
        ),
    ],
    deploys=[
        DeployFixture(
            key="flag-copy-deploy",
            id="dep-5502",
            version="v8.3.1",
            offset=timedelta(minutes=-10),
            commit_key="flag-copy-change",
            pr_number=2210,
        ),
    ],
    code_owners=[
        CodeOwnerFixture(path_pattern="app/clients/*", owners=["@checkout-team"]),
        CodeOwnerFixture(path_pattern="app/templates/*", owners=["@growth-team"]),
    ],
    logs=[
        LogFixture(
            key="upstream-timeout-1",
            offset=timedelta(minutes=-9),
            level="error",
            message="TimeoutError: request to shipping-rates-api timed out after 4000ms",
            trace_id="trc-c110",
            is_correlated=True,
        ),
        LogFixture(
            key="upstream-timeout-2",
            offset=timedelta(minutes=-4),
            level="error",
            message="TimeoutError: request to shipping-rates-api timed out after 4000ms",
            trace_id="trc-c119",
            is_correlated=True,
        ),
        LogFixture(
            key="upstream-status",
            offset=timedelta(minutes=-8),
            level="info",
            message="shipping-rates-api status page: investigating elevated response times",
            is_correlated=True,
        ),
    ],
    metrics=[
        MetricSeriesFixture(
            name="p99_latency_ms",
            unit="ms",
            baseline_value=420.0,
            points=[
                (timedelta(minutes=-30), 410.0),
                (timedelta(minutes=-15), 430.0),
                (timedelta(minutes=-11), 440.0),
                (timedelta(minutes=-10), 900.0),
                (timedelta(minutes=-8), 2100.0),
                (timedelta(minutes=-6), 3400.0),
                (timedelta(minutes=-4), 4600.0),
                (timedelta(minutes=-2), 4750.0),
                (timedelta(minutes=0), 4800.0),
            ],
        ),
        MetricSeriesFixture(
            name="shipping_rates_api_p99_latency_ms",
            unit="ms",
            baseline_value=180.0,
            service=UPSTREAM,
            points=[
                (timedelta(minutes=-30), 175.0),
                (timedelta(minutes=-11), 190.0),
                (timedelta(minutes=-10), 850.0),
                (timedelta(minutes=-6), 3200.0),
                (timedelta(minutes=-2), 4500.0),
                (timedelta(minutes=0), 4600.0),
            ],
        ),
    ],
    error_groups=[
        ErrorGroupFixture(
            key="upstream-timeout-group",
            fingerprint="TimeoutError@shipping_rates_client.py:55",
            title="TimeoutError calling shipping-rates-api",
            first_seen_offset=timedelta(minutes=-10),
            last_seen_offset=timedelta(seconds=-5),
            count=340,
            sample_stack_trace=(
                "TimeoutError: request to shipping-rates-api timed out after 4000ms\n"
                '  File "app/clients/shipping_rates_client.py", line 55, in get_rates'
            ),
            is_correlated=True,
        ),
    ],
    service_map=[
        ServiceEdgeFixture(from_service="web-frontend", to_service=SERVICE, call_kind="http"),
        ServiceEdgeFixture(from_service=SERVICE, to_service=UPSTREAM, call_kind="http"),
        ServiceEdgeFixture(from_service=SERVICE, to_service="postgres-checkout", call_kind="db"),
    ],
    expected_root_cause=(
        "checkout-api's own deploys are unrelated (a flagged copy-only change). The latency spike "
        "is caused by shipping-rates-api, a synchronous upstream dependency, degrading starting "
        "~10 minutes before the alert — its own p99 latency and checkout-api's p99 latency rise "
        "in lockstep, and shipping-rates-api's own status page confirms the incident."
    ),
    expected_correlated_keys=[
        "upstream-timeout-1",
        "upstream-timeout-2",
        "upstream-status",
        "upstream-timeout-group",
    ],
    expects_no_code_change=True,
)
