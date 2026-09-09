"""Playbook hint text, keyed by a lightweight alert classification. These are
*hints* injected into the phase-A prompt to bias tool-call order and search
window — not hardcoded conclusions. The agent can and does deviate (e.g. it
still widens its own window past the hint if it finds nothing, as required by
the resource-leak scenario). This is what keeps the system generalizing across
"alerts of different characteristics" instead of hardcoding four answers.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PlaybookKey(StrEnum):
    code_change = "code_change"
    """Default: an error/exception spike with no other strong signal. Check what shipped."""
    dependency = "dependency"
    """Latency/timeout language suggesting a downstream call is slow, not this service's code."""
    resource = "resource"
    """Memory/CPU/disk/OOM language suggesting a slow-building resource issue, possibly from
    a change well outside the alert's immediate time window."""
    config = "config"
    """Alert explicitly notes no recent deploy, or the message suggests a runtime toggle."""


@dataclass(frozen=True)
class Playbook:
    key: PlaybookKey
    narrow_window_minutes: int
    wide_window_hours: int
    hint: str


PLAYBOOKS: dict[PlaybookKey, Playbook] = {
    PlaybookKey.code_change: Playbook(
        key=PlaybookKey.code_change,
        narrow_window_minutes=30,
        wide_window_hours=6,
        hint=(
            "This looks like a code-change-driven incident (an error/exception spike). "
            "Start narrow: check recent deploys and merged PRs for the affected service in the "
            "last 30 minutes, cross-reference with the stack trace's file paths, and pull the "
            "matching error group and recent logs. If nothing in the narrow window correlates, "
            "widen before concluding."
        ),
    ),
    PlaybookKey.dependency: Playbook(
        key=PlaybookKey.dependency,
        narrow_window_minutes=30,
        wide_window_hours=6,
        hint=(
            "This looks latency/timeout-driven, which often means a downstream dependency, not "
            "this service's own code. Check the service map for what this service calls "
            "synchronously, then check THAT dependency's own metrics/logs/error groups for the "
            "same time window before assuming this service's own recent deploys are the cause. "
            "Don't stop at 'nothing changed here' — check what changed downstream."
        ),
    ),
    PlaybookKey.resource: Playbook(
        key=PlaybookKey.resource,
        narrow_window_minutes=30,
        wide_window_hours=48,
        hint=(
            "This looks like a resource exhaustion issue (memory/CPU/disk/OOM), which is often a "
            "SLOW build-up, not a step change from the most recent deploy. Pull the relevant "
            "metric over a WIDE window (hours to a couple of days) first to see the shape of the "
            "trend — a slow ramp points to a change well before the alert, not the most recent "
            "deploy. A recent deploy in the last few minutes is a common decoy in this class of "
            "incident; verify it actually touches memory/allocation behavior before trusting it."
        ),
    ),
    PlaybookKey.config: Playbook(
        key=PlaybookKey.config,
        narrow_window_minutes=30,
        wide_window_hours=6,
        hint=(
            "The alert notes no recent deploy, or nothing in code looks recent enough to explain "
            "this. Don't stop at GitHub — search logs for config, feature-flag, or audit-trail "
            "entries in the narrow window before the alert. Absence of a deploy is itself a "
            "finding, not a dead end."
        ),
    ),
}

_RESOURCE_KEYWORDS = ("oom", "memory", "out of memory", "cpu", "disk", "leak", "killed")
_DEPENDENCY_KEYWORDS = ("timeout", "timed out", "latency", "slow", "p99", "p95", "downstream")
# Deliberately multi-word: bare "flag" or "config" false-positives on ordinary paths/messages
# (a dependency-timeout stack trace through "app/config/db.py", a decoy PR titled "...behind
# a feature-flagged banner") — see PLAN.md's review-pass notes. Config is also checked LAST,
# after resource/dependency, since it should only win when nothing more specific matched.
_CONFIG_KEYWORDS = ("no deploy", "no recent deploy", "feature flag", "config change", "rollout")


def classify(title: str, message: str, stack_trace: str | None) -> Playbook:
    text = f"{title} {message} {stack_trace or ''}".lower()

    if any(kw in text for kw in _RESOURCE_KEYWORDS):
        return PLAYBOOKS[PlaybookKey.resource]
    if any(kw in text for kw in _DEPENDENCY_KEYWORDS):
        return PLAYBOOKS[PlaybookKey.dependency]
    if any(kw in text for kw in _CONFIG_KEYWORDS):
        return PLAYBOOKS[PlaybookKey.config]
    return PLAYBOOKS[PlaybookKey.code_change]
