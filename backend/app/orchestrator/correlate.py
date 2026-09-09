"""Deterministic correlation scoring — pure functions, no I/O, no LLM calls.

This is the "hybrid reasoning" half of the architecture: the LLM decides what
to investigate and writes the narrative, but *how strongly* a piece of
evidence actually correlates with the alert is computed here, not asserted by
the model.

It feeds exactly one thing: the synthesis guardrail (`grounding_warnings`). If
the model's top hypothesis doesn't cite the single most time/path-correlated
piece of evidence available, that's worth a caveat in the UI even if the
model's reasoning is otherwise fine — cheap, deterministic, and independent of
the model's own (possibly overconfident) narrative.

The scores themselves are deliberately NOT surfaced per-item in the evidence
rail. An earlier version of this docstring claimed they were; they never have
been. Showing a bare heuristic number next to real evidence invites an on-call
engineer to trust it as a ranking when it's three hand-tuned weights — its
honest job is to disagree with the model loudly enough to earn a warning, not
to look authoritative in a sidebar.
"""
from __future__ import annotations

from app.models.domain import Alert, EvidenceKind, Hypothesis
from app.models.domain import Evidence as EvidenceModel

_TIME_DECAY_MINUTES = 120.0
_PATH_OVERLAP_WEIGHT = 0.5
_ADJACENT_KIND_BONUS = 0.15


def score_evidence(evidence: EvidenceModel, alert: Alert) -> float:
    """Higher = more likely relevant to this specific alert. Not a probability —
    just a comparable relevance signal across evidence from a single investigation."""
    score = 0.0

    if evidence.occurred_at is not None:
        delta_minutes = abs((alert.fired_at - evidence.occurred_at).total_seconds()) / 60
        score += max(0.0, 1.0 - min(delta_minutes, _TIME_DECAY_MINUTES) / _TIME_DECAY_MINUTES)

    files_changed = evidence.detail.get("files_changed")
    if isinstance(files_changed, list) and alert.stack_trace:
        overlap = sum(
            1 for f in files_changed if isinstance(f, str) and f in alert.stack_trace
        )
        score += _PATH_OVERLAP_WEIGHT * overlap

    if evidence.kind in (EvidenceKind.error_group, EvidenceKind.log):
        score += _ADJACENT_KIND_BONUS

    return round(score, 3)


def rank_evidence(
    evidence_list: list[EvidenceModel], alert: Alert
) -> list[tuple[EvidenceModel, float]]:
    scored = [(e, score_evidence(e, alert)) for e in evidence_list]
    return sorted(scored, key=lambda pair: pair[1], reverse=True)


def grounding_warnings(
    hypotheses: list[Hypothesis],
    scored_evidence: list[tuple[EvidenceModel, float]],
    top_n: int = 1,
) -> list[str]:
    """Cheap sanity check: does the winning hypothesis cite the evidence our own
    deterministic scoring thinks is most relevant? A mismatch doesn't mean the
    model is wrong (it may have found something our simple heuristic can't
    see, e.g. the downstream-dependency scenario), but it's worth flagging."""
    if not hypotheses or not scored_evidence:
        return []

    top_candidates = [e for e, score in scored_evidence[:top_n] if score > 0]
    if not top_candidates:
        return []

    top_hypothesis = min(hypotheses, key=lambda h: h.rank)
    cited = set(top_hypothesis.evidence_ids)
    top_ids = {e.id for e in top_candidates}

    if not (top_ids & cited):
        titles = ", ".join(e.title for e in top_candidates)
        return [
            f"The top hypothesis doesn't cite the most time/path-correlated evidence "
            f"available ({titles}) — worth a second look."
        ]
    return []
