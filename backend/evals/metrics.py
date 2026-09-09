"""Scoring for one eval case, and reporting across a run. Pure functions given
an already-completed `Investigation` and `JudgeResult` — no CLI calls happen
here, so this whole module is fast-tested without spending API credit (see
tests/test_evals.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.fixtures.scenarios.spec import Scenario
from app.models.domain import EvidenceKind, Investigation
from evals.resolve import decoy_keys, resolve_all

_CODE_KINDS = {EvidenceKind.commit, EvidenceKind.pull_request, EvidenceKind.deploy}


@dataclass
class CaseResult:
    scenario_key: str
    status: str
    root_cause_correct: bool | None
    judge_explanation: str
    evidence_recall: float
    """Fraction of expected_correlated_keys the investigation actually gathered."""
    citation_precision: float | None
    """Of the top hypothesis's citations that map to an expected/decoy key, what
    fraction are expected (not decoy). None if it cited neither."""
    decoy_citations: int
    """How many decoy-key evidence items the top hypothesis cited outright."""
    hallucinated_citations: int
    """Citations (any hypothesis) that don't resolve to real evidence at all — should
    always be 0 given the schema-enum guardrail; a nonzero value is a real regression."""
    abstention_correct: bool | None
    """Only meaningful when the scenario expects no code-change cause: did the top
    hypothesis avoid blaming a decoy commit/PR/deploy? None when not applicable."""
    wall_time_ms: int | None
    total_cost_usd: float
    judge_cost_usd: float
    total_tool_calls: int
    warnings: list[str] = field(default_factory=list)


def score_case(
    scenario: Scenario,
    investigation: Investigation,
    *,
    judge_correct: bool | None,
    judge_explanation: str,
    judge_cost_usd: float,
) -> CaseResult:
    evidence_by_id = {e.id: e for e in investigation.evidence}
    resolved_expected = resolve_all(
        scenario, scenario.expected_correlated_keys, investigation.evidence
    )
    resolved_decoys = resolve_all(scenario, decoy_keys(scenario), investigation.evidence)

    gathered = sum(1 for ids in resolved_expected.values() if ids)
    evidence_recall = gathered / len(resolved_expected) if resolved_expected else 1.0

    expected_ids = {eid for ids in resolved_expected.values() for eid in ids}
    decoy_ids = {eid for ids in resolved_decoys.values() for eid in ids}

    top = min(investigation.hypotheses, key=lambda h: h.rank) if investigation.hypotheses else None
    cited = set(top.evidence_ids) if top else set()

    cited_expected = len(cited & expected_ids)
    cited_decoy = len(cited & decoy_ids)
    judged_citations = cited_expected + cited_decoy
    citation_precision = (cited_expected / judged_citations) if judged_citations else None

    all_cited = {eid for h in investigation.hypotheses for eid in h.evidence_ids}
    hallucinated = sum(1 for eid in all_cited if eid not in evidence_by_id)

    abstention_correct = None
    if scenario.expects_no_code_change and top is not None:
        code_decoy_ids = {
            eid
            for eid in decoy_ids
            if evidence_by_id.get(eid) and evidence_by_id[eid].kind in _CODE_KINDS
        }
        abstention_correct = len(cited & code_decoy_ids) == 0

    return CaseResult(
        scenario_key=scenario.key,
        status=investigation.status.value,
        root_cause_correct=judge_correct,
        judge_explanation=judge_explanation,
        evidence_recall=round(evidence_recall, 3),
        citation_precision=round(citation_precision, 3) if citation_precision is not None else None,
        decoy_citations=cited_decoy,
        hallucinated_citations=hallucinated,
        abstention_correct=abstention_correct,
        wall_time_ms=investigation.wall_time_ms,
        total_cost_usd=round(investigation.total_cost_usd, 4),
        judge_cost_usd=round(judge_cost_usd, 4),
        total_tool_calls=investigation.total_tool_calls,
        warnings=investigation.warnings,
    )


def format_report(results: list[CaseResult]) -> str:
    lines = ["=" * 100]
    for r in results:
        lines.append(f"{r.scenario_key:<24} status={r.status}")
        correct_str = (
            "N/A" if r.root_cause_correct is None else ("PASS" if r.root_cause_correct else "FAIL")
        )
        lines.append(f"  root_cause_correct   : {correct_str}")
        if r.root_cause_correct is False:
            lines.append(f"    judge explanation  : {r.judge_explanation}")
        lines.append(f"  evidence_recall      : {r.evidence_recall:.0%}")
        precision_str = "N/A" if r.citation_precision is None else f"{r.citation_precision:.0%}"
        lines.append(f"  citation_precision   : {precision_str}")
        lines.append(f"  decoy_citations      : {r.decoy_citations}")
        lines.append(f"  hallucinated_citations: {r.hallucinated_citations}")
        if r.abstention_correct is not None:
            lines.append(f"  abstention_correct   : {'PASS' if r.abstention_correct else 'FAIL'}")
        if r.warnings:
            lines.append(f"  guardrail_warnings   : {r.warnings}")
        lines.append(
            f"  cost=${r.total_cost_usd:.3f} (+${r.judge_cost_usd:.3f} judge)  "
            f"time={(r.wall_time_ms or 0) / 1000:.1f}s  tool_calls={r.total_tool_calls}"
        )
        lines.append("-" * 100)

    n = len(results)
    graded = [r for r in results if r.root_cause_correct is not None]
    accuracy = sum(1 for r in graded if r.root_cause_correct) / len(graded) if graded else 0.0
    avg_recall = sum(r.evidence_recall for r in results) / n if n else 0.0
    total_hallucinations = sum(r.hallucinated_citations for r in results)
    total_cost = sum(r.total_cost_usd + r.judge_cost_usd for r in results)
    abstention_cases = [r for r in results if r.abstention_correct is not None]
    abstention_rate = (
        sum(1 for r in abstention_cases if r.abstention_correct) / len(abstention_cases)
        if abstention_cases
        else None
    )

    lines.append(f"SUMMARY ({n} cases)")
    lines.append(f"  root-cause accuracy  : {accuracy:.0%}")
    lines.append(f"  avg evidence recall  : {avg_recall:.0%}")
    lines.append(f"  total hallucinations : {total_hallucinations}")
    if abstention_rate is not None:
        lines.append(
            f"  abstention accuracy  : {abstention_rate:.0%} ({len(abstention_cases)} cases)"
        )
    lines.append(f"  total cost           : ${total_cost:.2f}")
    lines.append("=" * 100)
    return "\n".join(lines)
