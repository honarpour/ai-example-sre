"""Local stdio MCP server exposing the GitHub and observability sources as tools.

This is the agent's *only* way to see evidence — the `claude` CLI subprocess is
launched with `--mcp-config` pointing at this server plus `--strict-mcp-config`
(no other MCP server is reachable) and `--disallowedTools` removing
`Bash`/`Edit`/`Write`/`NotebookEdit`/`Task`/`WebFetch`/`WebSearch` from the tool
set entirely, so the investigator is read-only by construction, not by
convention. See cli_agent.py, which owns those flags.

Which scenario's fixture data to serve, and what "now" means for materializing
its time-relative offsets, are fixed at process start via environment variables
(`SRE_SCENARIO_KEY`, `SRE_REFERENCE_TIME`) — the orchestrator spawns one server
process per investigation. `SRE_OBSERVABILITY_DATA_SOURCE=live` swaps the
observability half over to a real Prometheus/Loki/GlitchTip stack behind this
same tool surface (Phase 7b, implemented in `_sources()` below); the GitHub half
is still fixture-backed (Phase 7a, deferred).

Tool responses are kept intentionally small (dataclasses -> plain dicts, no raw
patches) so a multi-turn investigation doesn't blow the model's context on
verbose payloads — `get_pr_diff` returns a pre-summarized diff, never a raw
unified diff.
"""
from __future__ import annotations

import functools
import inspect
import os
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from app.fixtures.scenarios import get_scenario  # noqa: E402
from app.sources.base import GitHubSource, ObservabilitySource  # noqa: E402
from app.sources.mock import MockGitHubSource, MockObservabilitySource  # noqa: E402
from app.sources.observability_live import LiveObservabilitySource  # noqa: E402

mcp = MCPServer(name="sre-investigator-tools")


def _now() -> datetime:
    raw = os.environ.get("SRE_REFERENCE_TIME")
    return datetime.fromisoformat(raw) if raw else datetime.now(UTC)


def _sources() -> tuple[GitHubSource, ObservabilitySource]:
    """GitHub and observability are selected independently — see config.py's
    `data_source` vs. `observability_data_source` docstrings for why one flag
    can't express this project's actual Phase 7 state (observability live,
    GitHub still mock). Connection details arrive as env vars from
    `runner._write_mcp_config`, one MCP server subprocess per investigation."""
    scenario_key = os.environ.get("SRE_SCENARIO_KEY")
    if not scenario_key:
        raise RuntimeError("SRE_SCENARIO_KEY must be set to select a data source scenario")
    scenario = get_scenario(scenario_key)

    github: GitHubSource = MockGitHubSource(scenario, _now())

    obs: ObservabilitySource
    if os.environ.get("SRE_OBSERVABILITY_DATA_SOURCE") == "live":
        obs = LiveObservabilitySource(
            prometheus_url=os.environ.get("SRE_PROMETHEUS_URL", "http://localhost:9090"),
            loki_url=os.environ.get("SRE_LOKI_URL", "http://localhost:3100"),
            glitchtip_url=os.environ.get("SRE_GLITCHTIP_URL"),
            glitchtip_api_token=os.environ.get("SRE_GLITCHTIP_API_TOKEN"),
            glitchtip_org_slug=os.environ.get("SRE_GLITCHTIP_ORG_SLUG"),
            glitchtip_project_slug=os.environ.get("SRE_GLITCHTIP_PROJECT_SLUG"),
        )
    else:
        obs = MockObservabilitySource(scenario, _now())

    return github, obs


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _ser(value: Any) -> Any:
    """Recursively converts dataclasses (via `asdict`) and datetimes to
    JSON-safe values. Needs its own `dict` branch even though `asdict` already
    flattens nested dataclasses to plain dicts — `asdict` does NOT stringify
    datetimes inside those nested dicts/lists (e.g. MetricSeries.points, a list
    of {"timestamp": datetime, "value": float} dicts after asdict), so without
    this branch a nested timestamp silently passes through as a raw datetime
    object instead of an ISO string."""
    if isinstance(value, list):
        return [_ser(v) for v in value]
    if isinstance(value, dict):
        return {k: _ser(v) for k, v in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {k: _ser(v) for k, v in asdict(value).items()}
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _ser_list(value: list[Any]) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", _ser(value))


def _ser_one(value: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", _ser(value))


_tool_cache: dict[tuple[Any, ...], Any] = {}
_F = TypeVar("_F", bound=Callable[..., Any])


def _memoized(fn: _F) -> _F:
    """Caches a tool function's result by (tool name, its arguments, and the
    scenario/data-source env vars from `_sources()`). This process is spawned fresh
    per investigation (see the module docstring), so in practice this cache's
    lifetime is exactly one investigation, not shared across runs.

    This does NOT reduce Anthropic API token cost — the model still emits a
    tool_use and receives a tool_result of the same size whether we compute it
    fresh or serve it from cache; that round trip happens in the CLI's own
    agentic loop, upstream of this server. What it actually buys: (1) live mode
    (`SRE_OBSERVABILITY_DATA_SOURCE=live`) skips a redundant real HTTP round trip
    to Prometheus/Loki/GlitchTip when the agent re-asks something it already
    asked (a common pattern — re-checking a window after finding something new
    elsewhere), and (2) a live system can drift between two identical-looking
    queries a few seconds apart; caching guarantees the agent sees byte-identical
    evidence for a repeated question within one investigation, rather than two
    slightly different answers to what it thinks is the same question.

    The env vars are included in the key (not just the tool's own arguments)
    so this can't return a stale cross-scenario result if a server process is
    ever reused — defense in depth beyond the one-process-per-investigation
    invariant `_sources()` already relies on; it's also what keeps this test-safe,
    since pytest imports this module once and its tests share the module-level
    `_tool_cache` across scenario keys.

    An exception is deliberately never cached: `fn(**kwargs)` runs before the
    dict is written, so a raised error always propagates and always retries."""
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        key = (
            fn.__name__,
            tuple(sorted(bound.arguments.items())),
            os.environ.get("SRE_SCENARIO_KEY"),
            os.environ.get("SRE_REFERENCE_TIME"),
            os.environ.get("SRE_OBSERVABILITY_DATA_SOURCE"),
        )
        if key not in _tool_cache:
            _tool_cache[key] = fn(*args, **kwargs)
        return _tool_cache[key]

    wrapper.__signature__ = sig  # type: ignore[attr-defined]
    return cast("_F", wrapper)


@mcp.tool()
@_memoized
def github_list_recent_commits(service: str, since: str, until: str) -> list[dict[str, Any]]:
    """List commits to `service` between `since` and `until` (ISO 8601 timestamps)."""
    github, _ = _sources()
    return _ser_list(github.list_recent_commits(service, _parse(since), _parse(until)))


@mcp.tool()
@_memoized
def github_list_merged_prs(service: str, since: str, until: str) -> list[dict[str, Any]]:
    """List PRs merged into `service` between `since` and `until` (ISO 8601 timestamps)."""
    github, _ = _sources()
    return _ser_list(github.list_merged_prs(service, _parse(since), _parse(until)))


@mcp.tool()
@_memoized
def github_get_deploys(service: str, since: str, until: str) -> list[dict[str, Any]]:
    """List deploys of `service` between `since` and `until` (ISO 8601 timestamps)."""
    github, _ = _sources()
    return _ser_list(github.get_deploys(service, _parse(since), _parse(until)))


@mcp.tool()
@_memoized
def github_get_file_history(path: str, limit: int = 10) -> list[dict[str, Any]]:
    """Get recent commits that touched a specific file path, most recent first."""
    github, _ = _sources()
    return _ser_list(github.get_file_history(path, limit))


@mcp.tool()
@_memoized
def github_get_code_owners(service: str) -> list[dict[str, Any]]:
    """Get the code-owner mapping (path pattern -> owning team/individuals) for `service`."""
    github, _ = _sources()
    return _ser_list(github.get_code_owners(service))


@mcp.tool()
@_memoized
def github_get_pr_diff(pr_number: int) -> str:
    """Get a human-readable diff summary for a PR (not the raw patch)."""
    github, _ = _sources()
    return github.get_pr_diff(pr_number)


@mcp.tool()
@_memoized
def observability_query_metric(
    service: str, metric_name: str, since: str, until: str
) -> dict[str, Any]:
    """Query a named metric's time series for `service` between `since` and `until`."""
    _, obs = _sources()
    return _ser_one(obs.query_metric(service, metric_name, _parse(since), _parse(until)))


@mcp.tool()
@_memoized
def observability_search_logs(
    service: str, query: str, since: str, until: str, limit: int = 50
) -> list[dict[str, Any]]:
    """Search logs for `service` between `since` and `until`. Empty `query` returns all logs
    in the window. `query` matches case-insensitively against the log message."""
    _, obs = _sources()
    return _ser_list(obs.search_logs(service, query, _parse(since), _parse(until), limit))


@mcp.tool()
@_memoized
def observability_get_service_map(service: str) -> list[dict[str, Any]]:
    """Get the upstream/downstream service dependency edges for `service`."""
    _, obs = _sources()
    return _ser_list(obs.get_service_map(service))


@mcp.tool()
@_memoized
def observability_get_error_groups(service: str, since: str, until: str) -> list[dict[str, Any]]:
    """List grouped/deduplicated error clusters for `service` active between `since` and
    `until`, each with a sample stack trace and occurrence count."""
    _, obs = _sources()
    return _ser_list(obs.get_error_groups(service, _parse(since), _parse(until)))


@mcp.tool()
@_memoized
def observability_compare_baseline(service: str, metric_name: str, at: str) -> dict[str, float]:
    """Compare a metric's value at time `at` against its typical baseline. Returns
    {current, baseline, pct_change}."""
    _, obs = _sources()
    return obs.compare_baseline(service, metric_name, _parse(at))


if __name__ == "__main__":
    mcp.run(transport="stdio")
