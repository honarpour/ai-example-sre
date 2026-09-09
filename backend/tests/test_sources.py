from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.fixtures.scenarios import SCENARIOS
from app.sources.base import GitHubSource, ObservabilitySource
from app.sources.mock import build_mock_sources

NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
WIDE_SINCE = NOW - timedelta(days=2)
WIDE_UNTIL = NOW + timedelta(minutes=5)


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=lambda s: s.key)
def test_scenario_has_required_fields(scenario):
    assert scenario.key
    assert scenario.alert.service
    assert scenario.expected_root_cause
    assert scenario.expected_correlated_keys, "every scenario must tag its root-cause evidence"


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=lambda s: s.key)
def test_mock_sources_satisfy_protocols(scenario):
    github, obs = build_mock_sources(scenario, NOW)
    assert isinstance(github, GitHubSource)
    assert isinstance(obs, ObservabilitySource)


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=lambda s: s.key)
def test_all_tools_callable_with_wide_window(scenario):
    """Exercises every tool method against every scenario — the Phase 1 exit bar."""
    github, obs = build_mock_sources(scenario, NOW)
    service = scenario.alert.service

    commits = github.list_recent_commits(service, WIDE_SINCE, WIDE_UNTIL)
    prs = github.list_merged_prs(service, WIDE_SINCE, WIDE_UNTIL)
    deploys = github.get_deploys(service, WIDE_SINCE, WIDE_UNTIL)
    owners = github.get_code_owners(service)
    assert isinstance(commits, list)
    assert isinstance(prs, list)
    assert isinstance(deploys, list)
    assert isinstance(owners, list)

    if scenario.pull_requests:
        diff = github.get_pr_diff(scenario.pull_requests[0].number)
        assert diff and "No diff found" not in diff

    if scenario.commits:
        history = github.get_file_history(scenario.commits[0].files_changed[0])
        assert len(history) >= 1

    error_groups = obs.get_error_groups(service, WIDE_SINCE, WIDE_UNTIL)
    service_map = obs.get_service_map(service)
    assert isinstance(error_groups, list)
    assert isinstance(service_map, list)

    if scenario.metrics:
        series = obs.query_metric(service, scenario.metrics[0].name, WIDE_SINCE, WIDE_UNTIL)
        assert series.points, "metric query with a wide window must return points"
        baseline = obs.compare_baseline(service, scenario.metrics[0].name, NOW)
        assert "pct_change" in baseline

    logs = obs.search_logs(service, "", WIDE_SINCE, WIDE_UNTIL)
    assert isinstance(logs, list)


def test_narrow_window_misses_resource_leak_root_cause():
    """The resource-leak scenario's root cause is ~21h before the alert. A naive
    'last 30 minutes' window must NOT surface it — proving the fixture actually
    forces the agent to widen its search rather than trusting alert recency."""
    scenario = SCENARIOS["resource-leak"]
    github, _ = build_mock_sources(scenario, NOW)
    narrow_since = NOW - timedelta(minutes=30)

    prs = github.list_merged_prs(scenario.alert.service, narrow_since, NOW)
    pr_titles = {p.title for p in prs}
    assert "Cache rendered report templates in-process to cut render latency" not in pr_titles

    wide_prs = github.list_merged_prs(scenario.alert.service, NOW - timedelta(hours=24), NOW)
    wide_titles = {p.title for p in wide_prs}
    assert "Cache rendered report templates in-process to cut render latency" in wide_titles


def test_downstream_dependency_has_no_correlated_code_change():
    scenario = SCENARIOS["downstream-dependency"]
    assert scenario.expects_no_code_change
    correlated_prs = [p for p in scenario.pull_requests if p.is_correlated]
    correlated_commits = [c for c in scenario.commits if c.is_correlated]
    correlated_deploys = [d for d in scenario.deploys if d.is_correlated]
    assert not correlated_prs and not correlated_commits and not correlated_deploys


def test_config_flag_scenario_has_no_deploys():
    scenario = SCENARIOS["config-flag"]
    assert scenario.expects_no_code_change
    assert scenario.deploys == []


def test_log_search_filters_by_query_and_window():
    scenario = SCENARIOS["bad-deploy"]
    _, obs = build_mock_sources(scenario, NOW)
    results = obs.search_logs(
        scenario.alert.service, "QueuePool", NOW - timedelta(minutes=10), NOW
    )
    assert results
    assert all("QueuePool" in r.message for r in results)

    empty = obs.search_logs(
        scenario.alert.service, "QueuePool", NOW - timedelta(minutes=10), NOW - timedelta(minutes=6)
    )
    assert empty == []
