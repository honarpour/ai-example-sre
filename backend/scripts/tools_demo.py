"""Phase 1 exit check: call every source method against every scenario and print
the results. Not a test (no assertions) — a human-readable smoke check that the
fixture data reads like a real incident, not lorem ipsum. Run with `make tools-demo`.
"""
from __future__ import annotations

import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.fixtures.scenarios import SCENARIOS  # noqa: E402
from app.sources.mock import build_mock_sources  # noqa: E402

NOW = datetime.now(UTC)
WIDE_SINCE = NOW - timedelta(days=2)
WIDE_UNTIL = NOW + timedelta(minutes=5)


def _fmt(value: Any) -> str:
    if is_dataclass(value) and not isinstance(value, type):
        return str(asdict(value))
    if isinstance(value, list):
        return f"[{len(value)} items]" if not value else "\n    - " + "\n    - ".join(
            _fmt(v) for v in value
        )
    return str(value)


def main() -> None:
    for scenario in SCENARIOS.values():
        service = scenario.alert.service
        print("=" * 100)
        print(f"SCENARIO: {scenario.key} — {scenario.name}")
        print(f"  service={service} expects_no_code_change={scenario.expects_no_code_change}")
        print(f"  alert: {scenario.alert.title}")
        print(f"  message: {scenario.alert.message}")
        print()

        github, obs = build_mock_sources(scenario, NOW)

        print("-- github.list_recent_commits --")
        print("  " + _fmt(github.list_recent_commits(service, WIDE_SINCE, WIDE_UNTIL)))
        print("-- github.list_merged_prs --")
        print("  " + _fmt(github.list_merged_prs(service, WIDE_SINCE, WIDE_UNTIL)))
        print("-- github.get_deploys --")
        print("  " + _fmt(github.get_deploys(service, WIDE_SINCE, WIDE_UNTIL)))
        print("-- github.get_code_owners --")
        print("  " + _fmt(github.get_code_owners(service)))

        print("-- observability.get_error_groups --")
        print("  " + _fmt(obs.get_error_groups(service, WIDE_SINCE, WIDE_UNTIL)))
        print("-- observability.get_service_map --")
        print("  " + _fmt(obs.get_service_map(service)))
        print("-- observability.search_logs (query='') --")
        print("  " + _fmt(obs.search_logs(service, "", WIDE_SINCE, WIDE_UNTIL)))

        for m in scenario.metrics:
            print(f"-- observability.query_metric({m.name}) --")
            series = obs.query_metric(service, m.name, WIDE_SINCE, WIDE_UNTIL)
            print(f"  baseline={series.baseline_value} points={len(series.points)}")
            print(f"  compare_baseline(at=now): {obs.compare_baseline(service, m.name, NOW)}")

        print(f"\n  expected_root_cause: {scenario.expected_root_cause}")
        print(f"  expected_correlated_keys: {scenario.expected_correlated_keys}")
        print()


if __name__ == "__main__":
    main()
