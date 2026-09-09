"""Fast, deterministic tests for the eval scoring machinery — no CLI calls.
Builds synthetic Investigation objects directly rather than running the real
agent, so this suite stays part of the default `pytest` run."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.fixtures.scenarios import SCENARIOS
from app.models.domain import (
    Alert,
    AlertSource,
    Confidence,
    Evidence,
    EvidenceKind,
    Hypothesis,
    Investigation,
    InvestigationStatus,
    Severity,
)
from evals.metrics import score_case
from evals.resolve import all_fixture_keys, decoy_keys, resolve_key_to_evidence_ids


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=lambda s: s.key)
def test_decoy_keys_partition_all_keys(scenario):
    all_keys = {fk.key for fk in all_fixture_keys(scenario)}
    expected = set(scenario.expected_correlated_keys)
    decoys = set(decoy_keys(scenario))
    assert expected <= all_keys
    assert decoys == all_keys - expected
    assert expected.isdisjoint(decoys)


def test_resolve_key_to_evidence_ids_matches_by_natural_identifier():
    scenario = SCENARIOS["bad-deploy"]
    pr_evidence = Evidence(
        kind=EvidenceKind.pull_request,
        title="PR #4821: Reduce DB pool size",
        summary="...",
        detail={"number": 4821, "title": "Reduce DB pool size"},
    )
    other_evidence = Evidence(
        kind=EvidenceKind.pull_request,
        title="PR #4815: unrelated",
        summary="...",
        detail={"number": 4815, "title": "unrelated"},
    )
    ids = resolve_key_to_evidence_ids(scenario, "pool-shrink-pr", [pr_evidence, other_evidence])
    assert ids == [pr_evidence.id]


def test_resolve_key_to_evidence_ids_empty_when_not_gathered():
    scenario = SCENARIOS["bad-deploy"]
    assert resolve_key_to_evidence_ids(scenario, "pool-shrink-pr", []) == []


def _investigation(
    alert_scenario: str, evidence: list[Evidence], hypotheses: list[Hypothesis]
) -> Investigation:
    scenario = SCENARIOS[alert_scenario]
    alert = Alert(
        title=scenario.alert.title,
        service=scenario.alert.service,
        severity=Severity(scenario.alert.severity),
        message=scenario.alert.message,
        fired_at=datetime.now(UTC),
        source=AlertSource.manual,
        scenario=alert_scenario,
    )
    inv = Investigation(alert=alert, created_at=datetime.now(UTC))
    inv.evidence = evidence
    inv.hypotheses = hypotheses
    inv.status = InvestigationStatus.complete
    return inv


def test_score_case_perfect_run_scores_full_recall_and_precision():
    scenario = SCENARIOS["bad-deploy"]
    pr_evidence = Evidence(
        id="ev-pr",
        kind=EvidenceKind.pull_request,
        title="PR #4821",
        summary="...",
        detail={"number": 4821},
    )
    decoy_evidence = Evidence(
        id="ev-decoy",
        kind=EvidenceKind.pull_request,
        title="PR #4815",
        summary="...",
        detail={"number": 4815},
    )
    hyp = Hypothesis(
        rank=1,
        summary="PR #4821 caused it",
        reasoning="...",
        confidence=Confidence.high,
        evidence_ids=["ev-pr"],
    )
    inv = _investigation("bad-deploy", [pr_evidence, decoy_evidence], [hyp])

    result = score_case(
        scenario, inv, judge_correct=True, judge_explanation="", judge_cost_usd=0.01
    )

    assert result.root_cause_correct is True
    assert result.citation_precision == 1.0
    assert result.decoy_citations == 0
    assert result.hallucinated_citations == 0


def test_score_case_flags_decoy_citation():
    scenario = SCENARIOS["bad-deploy"]
    decoy_evidence = Evidence(
        id="ev-decoy",
        kind=EvidenceKind.pull_request,
        title="PR #4815",
        summary="...",
        detail={"number": 4815},
    )
    hyp = Hypothesis(
        rank=1,
        summary="wrong",
        reasoning="...",
        confidence=Confidence.low,
        evidence_ids=["ev-decoy"],
    )
    inv = _investigation("bad-deploy", [decoy_evidence], [hyp])

    result = score_case(
        scenario, inv, judge_correct=False, judge_explanation="wrong PR", judge_cost_usd=0.01
    )

    assert result.decoy_citations == 1
    assert result.citation_precision == 0.0


def test_score_case_flags_hallucinated_citation():
    scenario = SCENARIOS["bad-deploy"]
    hyp = Hypothesis(
        rank=1,
        summary="cites nothing real",
        reasoning="...",
        confidence=Confidence.low,
        evidence_ids=["does-not-exist"],
    )
    inv = _investigation("bad-deploy", [], [hyp])

    result = score_case(
        scenario, inv, judge_correct=False, judge_explanation="", judge_cost_usd=0.0
    )

    assert result.hallucinated_citations == 1


def test_score_case_abstention_correct_when_no_code_decoy_cited():
    scenario = SCENARIOS["downstream-dependency"]
    assert scenario.expects_no_code_change
    upstream_evidence = Evidence(
        id="ev-upstream", kind=EvidenceKind.error_group, title="timeout", summary="...", detail={}
    )
    hyp = Hypothesis(
        rank=1, summary="upstream dependency", reasoning="...", confidence=Confidence.high,
        evidence_ids=["ev-upstream"],
    )
    inv = _investigation("downstream-dependency", [upstream_evidence], [hyp])

    result = score_case(scenario, inv, judge_correct=True, judge_explanation="", judge_cost_usd=0.0)

    assert result.abstention_correct is True


def test_score_case_abstention_incorrect_when_decoy_deploy_blamed():
    scenario = SCENARIOS["downstream-dependency"]
    decoy_pr = SCENARIOS["downstream-dependency"].pull_requests[0]
    pr_evidence = Evidence(
        id="ev-decoy-pr",
        kind=EvidenceKind.pull_request,
        title="decoy PR",
        summary="...",
        detail={"number": decoy_pr.number},
    )
    hyp = Hypothesis(
        rank=1, summary="blamed the deploy", reasoning="...", confidence=Confidence.high,
        evidence_ids=["ev-decoy-pr"],
    )
    inv = _investigation("downstream-dependency", [pr_evidence], [hyp])

    result = score_case(
        scenario, inv, judge_correct=False, judge_explanation="", judge_cost_usd=0.0
    )

    assert result.abstention_correct is False
