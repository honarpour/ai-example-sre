"""Exercises the MCP tool server the same way the `claude` CLI will: through
`call_tool`, not by calling the underlying Python functions directly. This is
what actually proves the tool schemas and JSON serialization work end to end.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest

os.environ["SRE_SCENARIO_KEY"] = "bad-deploy"
os.environ["SRE_REFERENCE_TIME"] = "2026-08-29T12:00:00+00:00"

from app.mcp_server import server as mcp_server_module  # noqa: E402
from app.mcp_server.server import _ser, mcp  # noqa: E402

WIDE_SINCE = "2026-08-27T12:00:00+00:00"
WIDE_UNTIL = "2026-08-29T12:05:00+00:00"


def _result_json(result):
    assert not result.is_error, result.content
    if result.structured_content is not None:
        return result.structured_content.get("result", result.structured_content)
    (block,) = result.content
    return json.loads(block.text)


@pytest.fixture(autouse=True)
def _scenario_env(monkeypatch):
    monkeypatch.setenv("SRE_SCENARIO_KEY", "bad-deploy")
    monkeypatch.setenv("SRE_REFERENCE_TIME", "2026-08-29T12:00:00+00:00")
    # _tool_cache is module-level and would otherwise leak between tests in this same
    # pytest process (unlike production, where one server process = one investigation).
    mcp_server_module._tool_cache.clear()


async def test_list_tools_exposes_all_eleven_tools():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "github_list_recent_commits",
        "github_list_merged_prs",
        "github_get_deploys",
        "github_get_file_history",
        "github_get_code_owners",
        "github_get_pr_diff",
        "observability_query_metric",
        "observability_search_logs",
        "observability_get_service_map",
        "observability_get_error_groups",
        "observability_compare_baseline",
    }


async def test_github_list_merged_prs_via_call_tool():
    result = await mcp.call_tool(
        "github_list_merged_prs",
        {"service": "payments-api", "since": WIDE_SINCE, "until": WIDE_UNTIL},
    )
    prs = _result_json(result)
    assert any(p["number"] == 4821 for p in prs)


async def test_observability_query_metric_via_call_tool():
    result = await mcp.call_tool(
        "observability_query_metric",
        {
            "service": "payments-api",
            "metric_name": "error_rate",
            "since": WIDE_SINCE,
            "until": WIDE_UNTIL,
        },
    )
    series = _result_json(result)
    assert series["name"] == "error_rate"
    assert len(series["points"]) == 10


async def test_github_get_pr_diff_returns_summary_not_raw_patch():
    result = await mcp.call_tool("github_get_pr_diff", {"pr_number": 4821})
    (block,) = result.content
    assert "pool_size" in block.text
    assert "diff --git" not in block.text


def test_ser_stringifies_datetime_nested_inside_a_plain_dict():
    """Regression test: `asdict()` flattens nested dataclasses to plain dicts but
    does NOT stringify a datetime living inside one of those dicts (e.g.
    MetricSeries.points, a list of {"timestamp": datetime, ...} dicts after
    asdict) — `_ser` needs its own dict-recursion branch to catch that."""
    now = datetime.now(UTC)
    nested = {"timestamp": now, "value": 1.0}
    result = _ser([nested])
    assert result == [{"timestamp": now.isoformat(), "value": 1.0}]


async def test_unknown_scenario_env_raises_cleanly(monkeypatch):
    from mcp.server.mcpserver.exceptions import UnexpectedToolError

    monkeypatch.setenv("SRE_SCENARIO_KEY", "not-a-real-scenario")
    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool(
            "github_list_merged_prs",
            {"service": "payments-api", "since": WIDE_SINCE, "until": WIDE_UNTIL},
        )


async def test_identical_calls_are_served_from_cache(monkeypatch):
    """Two identical calls should hit the underlying source exactly once —
    the second is served from `_tool_cache`, not recomputed."""
    from app.sources.mock import MockGitHubSource

    calls = []
    original = MockGitHubSource.list_merged_prs

    def counting(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MockGitHubSource, "list_merged_prs", counting)

    args = {"service": "payments-api", "since": WIDE_SINCE, "until": WIDE_UNTIL}
    first = _result_json(await mcp.call_tool("github_list_merged_prs", args))
    second = _result_json(await mcp.call_tool("github_list_merged_prs", args))

    assert first == second
    assert len(calls) == 1


async def test_different_args_are_not_conflated_in_cache():
    result_a = _result_json(
        await mcp.call_tool(
            "github_list_merged_prs",
            {"service": "payments-api", "since": WIDE_SINCE, "until": WIDE_UNTIL},
        )
    )
    result_b = _result_json(
        await mcp.call_tool(
            "github_list_merged_prs",
            {"service": "notifications-api", "since": WIDE_SINCE, "until": WIDE_UNTIL},
        )
    )
    assert result_a != result_b


async def test_cache_is_scoped_per_scenario_not_shared(monkeypatch):
    """The cache key includes SRE_SCENARIO_KEY specifically so a module-level cache
    (shared across this whole pytest process) can't leak one scenario's answer into
    another's — the real risk of keying only on the tool's own arguments."""
    args = {"service": "payments-api", "since": WIDE_SINCE, "until": WIDE_UNTIL}

    monkeypatch.setenv("SRE_SCENARIO_KEY", "bad-deploy")
    bad_deploy = _result_json(await mcp.call_tool("github_list_merged_prs", args))

    monkeypatch.setenv("SRE_SCENARIO_KEY", "config-flag")
    config_flag = _result_json(await mcp.call_tool("github_list_merged_prs", args))

    assert bad_deploy != config_flag


async def test_exceptions_are_never_cached(monkeypatch):
    """A failed call must not poison the cache for a subsequent, valid call with the
    exact same arguments once the underlying condition is fixed."""
    from mcp.server.mcpserver.exceptions import UnexpectedToolError

    monkeypatch.setenv("SRE_SCENARIO_KEY", "not-a-real-scenario-xyz")
    args = {"service": "payments-api", "since": WIDE_SINCE, "until": WIDE_UNTIL}
    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool("github_list_merged_prs", args)

    monkeypatch.setenv("SRE_SCENARIO_KEY", "bad-deploy")
    result = _result_json(await mcp.call_tool("github_list_merged_prs", args))
    assert isinstance(result, list)
