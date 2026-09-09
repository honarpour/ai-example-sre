"""Maps a fixture's stable `key` (e.g. "pool-shrink-pr", defined once in
app/fixtures/scenarios/*.py) to the actual `Evidence` a live investigation
run produced for it. Evidence IDs are random per run, so scoring against
`scenario.expected_correlated_keys` needs a bridge — this is it.

The bridge is each fixture kind's one natural identifier that survives the
trip from fixture -> mock source -> MCP tool result -> Evidence.detail:
commit sha, PR number, deploy id, error-group fingerprint. Logs have no such
identifier in our fixtures (two log lines can share identical text — see
bad-deploy's two QueuePool lines), so a log key resolves to *every* Evidence
with a matching message; that's fine for recall ("was this signal gathered
at all") even though it can't disambiguate which specific line was cited.

Pure functions, no I/O — fully unit-testable without spawning the CLI.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.fixtures.scenarios.spec import Scenario
from app.models.domain import Evidence


@dataclass(frozen=True)
class FixtureKey:
    key: str
    kind: str  # matches EvidenceKind values: commit, pull_request, deploy, log, error_group


def all_fixture_keys(scenario: Scenario) -> list[FixtureKey]:
    """Every key this scenario defines, across all evidence-producing fixture
    lists — the universe a decoy set is computed against."""
    keys: list[FixtureKey] = []
    keys += [FixtureKey(c.key, "commit") for c in scenario.commits]
    keys += [FixtureKey(p.key, "pull_request") for p in scenario.pull_requests]
    keys += [FixtureKey(d.key, "deploy") for d in scenario.deploys]
    keys += [FixtureKey(log_fixture.key, "log") for log_fixture in scenario.logs]
    keys += [FixtureKey(e.key, "error_group") for e in scenario.error_groups]
    return keys


def decoy_keys(scenario: Scenario) -> list[str]:
    """Keys NOT in expected_correlated_keys — the things a good investigation
    should gather (it's real data) but should NOT cite as the root cause."""
    expected = set(scenario.expected_correlated_keys)
    return [fk.key for fk in all_fixture_keys(scenario) if fk.key not in expected]


def _natural_id(scenario: Scenario, key: str) -> tuple[str, object] | None:
    """Returns (evidence.detail field name, expected value) for a fixture key."""
    for c in scenario.commits:
        if c.key == key:
            return ("sha", c.sha)
    for p in scenario.pull_requests:
        if p.key == key:
            return ("number", p.number)
    for d in scenario.deploys:
        if d.key == key:
            return ("id", d.id)
    for log_fixture in scenario.logs:
        if log_fixture.key == key:
            return ("message", log_fixture.message)
    for e in scenario.error_groups:
        if e.key == key:
            return ("fingerprint", e.fingerprint)
    return None


def resolve_key_to_evidence_ids(
    scenario: Scenario, key: str, evidence: list[Evidence]
) -> list[str]:
    """All Evidence ids matching this fixture key's natural identifier. Empty
    if the investigation never gathered this evidence at all."""
    natural = _natural_id(scenario, key)
    if natural is None:
        return []
    field, value = natural
    return [e.id for e in evidence if e.detail.get(field) == value]


def resolve_all(
    scenario: Scenario, keys: list[str], evidence: list[Evidence]
) -> dict[str, list[str]]:
    return {key: resolve_key_to_evidence_ids(scenario, key, evidence) for key in keys}
