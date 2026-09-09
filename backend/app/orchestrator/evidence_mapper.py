"""Maps a raw MCP tool call (name + input + result) into zero or more `Evidence`
records, deterministically. This is what makes the evidence rail hallucination-
proof: nothing appears as evidence unless a real tool call actually returned
it. The LLM only ever *cites* evidence IDs we've already created here — it
never authors evidence content itself (see runner.py's evidence-ID enum).

Supplementary/detail-fetch tools (`get_pr_diff`, `get_file_history`,
`get_code_owners`) don't produce new evidence records — they're follow-ups on
evidence the agent already has, and materializing them separately would just
duplicate the evidence rail with near-identical entries.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.domain import Evidence, EvidenceKind

MCP_TOOL_PREFIX = "mcp__sre_tools__"


def bare_tool_name(mcp_tool_name: str) -> str:
    return mcp_tool_name.removeprefix(MCP_TOOL_PREFIX)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _commit_evidence(item: dict[str, Any]) -> Evidence:
    return Evidence(
        kind=EvidenceKind.commit,
        title=f"Commit {item.get('sha', '')[:7]}: {item.get('message', '')}",
        summary=item.get("message", ""),
        detail=item,
        occurred_at=_parse_dt(item.get("authored_at")),
        source_url=item.get("url"),
    )


def _pr_evidence(item: dict[str, Any]) -> Evidence:
    return Evidence(
        kind=EvidenceKind.pull_request,
        title=f"PR #{item.get('number')}: {item.get('title', '')}",
        summary=item.get("diff_summary", ""),
        detail=item,
        occurred_at=_parse_dt(item.get("merged_at")),
        source_url=item.get("url"),
    )


def _deploy_evidence(item: dict[str, Any]) -> Evidence:
    return Evidence(
        kind=EvidenceKind.deploy,
        title=f"Deploy {item.get('version', '')} ({item.get('id', '')})",
        summary=f"service={item.get('service')} status={item.get('status')} "
        f"pr=#{item.get('pr_number')}",
        detail=item,
        occurred_at=_parse_dt(item.get("deployed_at")),
        source_url=item.get("url"),
    )


def _log_evidence(item: dict[str, Any]) -> Evidence:
    return Evidence(
        kind=EvidenceKind.log,
        title=f"[{item.get('level', '?').upper()}] {item.get('service', '')} log",
        summary=item.get("message", ""),
        detail=item,
        occurred_at=_parse_dt(item.get("timestamp")),
        source_url=None,
    )


def _error_group_evidence(item: dict[str, Any]) -> Evidence:
    return Evidence(
        kind=EvidenceKind.error_group,
        title=f"{item.get('title', '')} ({item.get('count', 0)}x)",
        summary=item.get("sample_stack_trace", "")[:300],
        detail=item,
        occurred_at=_parse_dt(item.get("last_seen")),
        source_url=None,
    )


def _service_map_evidence(item: dict[str, Any]) -> Evidence:
    return Evidence(
        kind=EvidenceKind.service_map,
        title=f"{item.get('from_service')} -> {item.get('to_service')} ({item.get('call_kind')})",
        summary=f"Service dependency edge, call_kind={item.get('call_kind')}",
        detail=item,
        occurred_at=None,
        source_url=None,
    )


def _metric_series_evidence(item: dict[str, Any], tool_input: dict[str, Any]) -> Evidence:
    points = item.get("points", [])
    last_ts = _parse_dt(points[-1]["timestamp"]) if points else None
    return Evidence(
        kind=EvidenceKind.metric,
        title=f"Metric: {item.get('name', tool_input.get('metric_name', '?'))}",
        summary=f"{len(points)} points, baseline={item.get('baseline_value')} "
        f"{item.get('unit', '')}",
        detail=item,
        occurred_at=last_ts,
        source_url=None,
    )


def _baseline_comparison_evidence(item: dict[str, Any], tool_input: dict[str, Any]) -> Evidence:
    metric_name = tool_input.get("metric_name", "?")
    at = _parse_dt(tool_input.get("at"))
    return Evidence(
        kind=EvidenceKind.metric,
        title=f"Baseline comparison: {metric_name}",
        summary=(
            f"current={item.get('current')} baseline={item.get('baseline')} "
            f"pct_change={item.get('pct_change')}%"
        ),
        detail={**item, "metric_name": metric_name, "service": tool_input.get("service")},
        occurred_at=at,
        source_url=None,
    )


_LIST_MAPPERS = {
    "github_list_recent_commits": _commit_evidence,
    "github_list_merged_prs": _pr_evidence,
    "github_get_deploys": _deploy_evidence,
    "observability_search_logs": _log_evidence,
    "observability_get_error_groups": _error_group_evidence,
    "observability_get_service_map": _service_map_evidence,
}

_SINGLE_MAPPERS = {
    "observability_query_metric": _metric_series_evidence,
    "observability_compare_baseline": _baseline_comparison_evidence,
}

# Detail-fetch tools that intentionally produce no new evidence records.
_NO_EVIDENCE_TOOLS = {"github_get_pr_diff", "github_get_file_history", "github_get_code_owners"}


def map_tool_result_to_evidence(
    mcp_tool_name: str, tool_input: dict[str, Any], output: Any
) -> list[Evidence]:
    name = bare_tool_name(mcp_tool_name)

    if name in _NO_EVIDENCE_TOOLS:
        return []

    if name in _LIST_MAPPERS and isinstance(output, list):
        mapper = _LIST_MAPPERS[name]
        return [mapper(item) for item in output if isinstance(item, dict)]

    if name in _SINGLE_MAPPERS and isinstance(output, dict):
        return [_SINGLE_MAPPERS[name](output, tool_input)]

    return []
