"""Deterministic triage: turn an alert into a starting investigation brief.
Classification and window sizing are cheap deterministic heuristics (see
playbooks.py) — no LLM call needed here, which keeps triage instant and
free, and keeps the expensive agent loop focused on evidence-gathering rather
than re-deriving "what kind of alert is this" from scratch every time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.domain import Alert
from app.orchestrator.playbooks import Playbook, classify


@dataclass
class TriageResult:
    playbook: Playbook
    narrow_since: datetime
    narrow_until: datetime
    wide_since: datetime
    wide_until: datetime


def triage(alert: Alert) -> TriageResult:
    playbook = classify(alert.title, alert.message, alert.stack_trace)
    until = alert.fired_at + timedelta(minutes=2)
    return TriageResult(
        playbook=playbook,
        narrow_since=alert.fired_at - timedelta(minutes=playbook.narrow_window_minutes),
        narrow_until=until,
        wide_since=alert.fired_at - timedelta(hours=playbook.wide_window_hours),
        wide_until=until,
    )
