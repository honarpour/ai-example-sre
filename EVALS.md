# Eval Framework

`make eval` runs a real investigation against each of the four fixture scenarios concurrently
(gated by the same `max_concurrent_investigations` semaphore production uses), judges root-cause
accuracy with an isolated LLM call, scores evidence handling deterministically, and prints a
report. Costs real API credit (~$1.20–1.50 for all four) — this is a deliberate command, never
part of the fast test suite (`make test`).

## Why scenarios *are* the eval cases

The original plan called for `evals/cases/*.json` files separate from the fixtures. Once the
fixtures existed (`app/fixtures/scenarios/*.py`), each `Scenario` already carried
`expected_root_cause`, `expected_correlated_keys`, and `expects_no_code_change` — fields added
in Phase 1 specifically so the eval harness could consume them later. Writing a second set of
case files would have duplicated that data and let the two drift. `evals/run.py` iterates
`SCENARIOS` directly instead. The trade-off: eval cases are exactly the four demo scenarios today,
not the wider variant set (shifted timing, ambiguous evidence) the original plan sketched — see
**Scaling this** below for where that goes next.

## What's measured, and how

| Metric | How | Why this design |
|---|---|---|
| **Root-cause accuracy** | An isolated `claude` call (no tools, no MCP, fresh session — `evals/judge.py`) compares the investigation's TL;DR + top hypothesis's reasoning against `scenario.expected_root_cause`, judging substance not wording. | A model judging its own investigation from inside the same session would be grading its own homework. The judge gets only the conclusion, not the evidence trail, and has no tools — it can't re-investigate, only compare. |
| **Evidence recall** | Deterministic: for each `expected_correlated_keys` entry, was matching `Evidence` actually gathered? (`evals/resolve.py` maps a fixture's stable key — commit sha, PR number, deploy id, error-group fingerprint — to real `Evidence.id`s from the run, since those are random per run.) | No LLM judgment needed — either the tool call happened and produced the evidence, or it didn't. |
| **Citation precision** | Of the winning hypothesis's cited evidence, what fraction are `expected_correlated_keys` vs. decoy keys? | Rewards citing the *right* evidence, not just *any* evidence — a hypothesis can have high recall (gathered everything) and still cite the wrong things. |
| **Decoy citations** | Count of decoy-key evidence cited by the winning hypothesis. | Every scenario ships a deliberate decoy (an unrelated deploy, a flagged copy change, a hotfix). This is the most direct signal of "did the agent fall for the trap." |
| **Hallucinated citations** | Citations that don't resolve to any real `Evidence.id` at all. | Should structurally always be 0 — the phase-B synthesis schema's evidence-ID enum makes this a *schema violation*, not just bad practice. A nonzero count here means that guardrail broke, which is worth knowing immediately. |
| **Abstention correctness** | For `expects_no_code_change` scenarios (downstream-dependency, config-flag): did the winning hypothesis avoid citing a decoy commit/PR/deploy as its evidence? | The two hardest scenarios in the suite are the ones where the *right* answer is "not a code change." This is the one metric that would catch a regression toward "always blame the most recent deploy." |
| **Cost / latency / tool calls** | Read directly off the completed `Investigation`. | Already tracked for the product's own cost footer (Phase 4); reused here for free. |

`evals/metrics.py` is pure functions — given an `Investigation` and a judge verdict, no I/O — so
it's covered by 11 fast unit tests (`tests/test_evals.py`) that never spend API credit. Only
`evals/run.py` (the orchestration loop) and `evals/judge.py` (the actual LLM call) touch the CLI.

## Reading a result

This is an actual case from the first full run (2026-08-29), not a hypothetical:

```
bad-deploy               status=complete
  root_cause_correct   : PASS
  evidence_recall      : 67%
  citation_precision   : 80%
  decoy_citations      : 1
  hallucinated_citations: 0
  cost=$0.262 (+$0.143 judge)  time=107.3s  tool_calls=22
```

Root cause correct, but only 67% evidence recall and one decoy citation — worth reading closely
even though the headline verdict is PASS. A case that's right on the conclusion while still
citing something it shouldn't have (or not gathering something it should have) is exactly the
kind of result a binary pass/fail would hide.

## A real result from the first full run, and what it exposed about the metric

The first `make eval` run (2026-08-29, `evals/results/eval-20260829T202655Z.json`) scored
**100% root-cause accuracy** across all four scenarios — including both `expects_no_code_change`
cases — but **0% abstention accuracy** (0/2). Reading the judge's own explanations for those two
"failing" cases:

> downstream-dependency: "...correctly rules out checkout-api's own deploy as
> coincidental/unrelated (text-only copy change)..."

> config-flag: "...explicitly ruling out a code deploy, and notes PR #3390 as a merged-but-
> undeployed fix..."

The model got both right. `abstention_correct` still failed them because the metric, as coded,
flags *any* citation of decoy evidence in the winning hypothesis's `evidence_ids` — and the model
cites the decoy PR/deploy as part of *explaining why it's not the cause*, which is exactly the
reasoning we want, not a mistake. The schema doesn't currently distinguish "evidence supporting
this hypothesis" from "evidence considered and ruled out," so a single `evidence_ids` list can't
tell the difference and the metric can't either.

This is being left as-is rather than patched reactively, for two reasons: first, this project
already hit one live regression from a rushed schema change (adding a required field made the
model stop returning `suggested_actions` at all), so a same-day second schema edit without a
full re-verification pass is exactly the kind of change that needs care, not speed. Second, and
more importantly, this is a better argument for
**why an eval harness matters** than a clean run would have been — it caught a real gap between
"the metric says fail" and "the behavior is actually correct" on the very first execution, which
is the whole point of building one instead of trusting a demo. The fix, when done properly, is a
schema change: split `evidence_ids` into something like `supporting_evidence_ids` and
`ruled_out_evidence_ids` on `Hypothesis`, so refuting a decoy is structurally distinguishable
from being fooled by it — then `abstention_correct` can check the right list instead of guessing
from one merged one.

## Scaling this

**More cases, not just more scenarios.** The highest-value next step is variants of the
existing four: shifted timing (does recall degrade if the causal PR merged 3 hours earlier
than modeled?), added noise (a second decoy in the same window), and genuinely ambiguous cases
where the correct hypothesis is *low confidence* — right now nothing in the suite scores
"appropriately uncertain" as a pass condition.

**From production traces, once there's a production.** Today's ground truth is hand-authored
because the fixtures are hand-authored. Once real incidents flow through the system, the same
`InvestigationFeedback` capture built in Phase 4 (👍/👎 + "what was the actual root cause") is
already the raw material for a growing golden set — a 👎 with a supplied root cause is a
candidate eval case waiting to be reviewed and added, no new capture mechanism needed.

**Judge calibration.** The current judge is a single unvalidated `claude` call. Before trusting
it for regression-gating in CI, it needs calibration against human-labeled agreement (does the
judge's PASS/FAIL match what an SRE would actually say?) on a sample large enough to compute
inter-rater agreement — not assumed correct because it's structured output.

**CI integration.** `make eval` is manual today because of cost and runtime. A regression-gate
version would run only on changes to `app/orchestrator/`, `app/fixtures/`, or the prompts
themselves — not on every commit — and would compare against the previous run's scores rather
than a fixed bar, so a change that trades recall for precision is visible, not just pass/fail.
