"""Eval harness entrypoint: `make eval`. Runs a real investigation for every
scenario, judges root-cause accuracy with an isolated LLM call, scores
evidence precision/recall/hallucination/abstention deterministically, prints
a report, and writes a JSON results file for tracking over time.

Costs real API credit (~4 investigations + 4 judge calls, roughly $1.20-1.50 total, as
measured) — this is a deliberate `make eval` command, never run as part of the fast
test suite. Cases run concurrently (see `main()`), gated by the same
`max_concurrent_investigations` semaphore `runner.py` uses in production.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.fixtures.scenarios import SCENARIOS  # noqa: E402
from app.models.domain import Alert, AlertSource, Investigation, Severity  # noqa: E402
from app.orchestrator.runner import run_investigation  # noqa: E402
from app.store import store  # noqa: E402
from evals.judge import judge_root_cause  # noqa: E402
from evals.metrics import CaseResult, format_report, score_case  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"
JUDGE_TIMEOUT_S = 60


async def run_case(scenario_key: str) -> CaseResult:
    scenario = SCENARIOS[scenario_key]
    alert = Alert(
        title=scenario.alert.title,
        service=scenario.alert.service,
        severity=Severity(scenario.alert.severity),
        message=scenario.alert.message,
        stack_trace=scenario.alert.stack_trace,
        fired_at=datetime.now(UTC),
        source=AlertSource.manual,
        scenario=scenario_key,
    )
    investigation = Investigation(alert=alert, created_at=datetime.now(UTC))
    store.create(investigation)

    print(f"[{scenario_key}] investigating...", flush=True)
    await run_investigation(investigation.id)
    result = store.get(investigation.id)
    assert result is not None

    if result.status.value != "complete" or not result.hypotheses:
        print(
            f"[{scenario_key}] did not complete cleanly (status={result.status.value})",
            flush=True,
        )
        return score_case(
            scenario, result, judge_correct=None, judge_explanation="", judge_cost_usd=0.0
        )

    top = min(result.hypotheses, key=lambda h: h.rank)
    print(f"[{scenario_key}] judging...", flush=True)
    judged = await judge_root_cause(
        reference_root_cause=scenario.expected_root_cause,
        candidate_tldr=result.tldr or "",
        candidate_reasoning=top.reasoning,
        timeout_s=JUDGE_TIMEOUT_S,
    )

    return score_case(
        scenario,
        result,
        judge_correct=judged.correct,
        judge_explanation=judged.explanation,
        judge_cost_usd=judged.cost_usd,
    )


async def main() -> None:
    started = time.monotonic()
    # Concurrent, not sequential: run_investigation is already gated by
    # settings.max_concurrent_investigations (see orchestrator/runner.py's semaphore),
    # so running every case's coroutine at once is safe and roughly halves wall time
    # at the same total cost — the print statements below may interleave across cases.
    results = await asyncio.gather(*(run_case(key) for key in SCENARIOS))
    elapsed = time.monotonic() - started

    report = format_report(results)
    print("\n" + report)
    print(f"\nTotal wall time: {elapsed:.0f}s")

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"eval-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(
        json.dumps([r.__dict__ for r in results], indent=2, default=str)
    )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
