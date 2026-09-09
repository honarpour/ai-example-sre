"""Core domain models. These are the single source of truth for the API contract —
TypeScript types are generated from the OpenAPI schema derived from these models
(see `make types`). Do not hand-maintain a parallel TS definition.
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _id() -> str:
    return uuid4().hex[:12]


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class AlertSource(StrEnum):
    webhook = "webhook"
    manual = "manual"


class Alert(BaseModel):
    id: str = Field(default_factory=_id)
    title: str
    service: str
    severity: Severity
    message: str
    """Raw alert body — e.g. an error rate spike description or an exception summary."""
    stack_trace: str | None = None
    fired_at: datetime
    source: AlertSource = AlertSource.manual
    scenario: str | None = None
    """Which fixture scenario this alert was created from, if any (drives mock data)."""

    @field_validator("fired_at")
    @classmethod
    def _ensure_timezone_aware(cls, value: datetime) -> datetime:
        """A tz-naive `fired_at` (a raw webhook payload with no offset, e.g.
        "2026-08-29T10:00:00") would otherwise crash every mock-source comparison
        against tz-aware fixture timestamps later — coerce to UTC here, once,
        rather than trust every caller to remember."""
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class EvidenceKind(StrEnum):
    commit = "commit"
    pull_request = "pull_request"
    deploy = "deploy"
    code_owner = "code_owner"
    log = "log"
    metric = "metric"
    error_group = "error_group"
    service_map = "service_map"


class Evidence(BaseModel):
    id: str = Field(default_factory=_id)
    kind: EvidenceKind
    title: str
    summary: str
    detail: dict[str, object]
    """Raw structured payload (diff, log lines, metric series, etc.) for the evidence rail."""
    occurred_at: datetime | None = None
    source_url: str | None = None
    """Link back to the 'real' artifact (GitHub PR URL, dashboard URL) when available."""


class AgentStepStatus(StrEnum):
    running = "running"
    complete = "complete"
    error = "error"


class AgentStep(BaseModel):
    id: str = Field(default_factory=_id)
    label: str
    """Human-readable summary, e.g. 'Searching recent deploys for payments-api'."""
    tool_name: str | None = None
    tool_input: dict[str, object] | None = None
    tool_output_summary: str | None = None
    status: AgentStepStatus
    started_at: datetime
    finished_at: datetime | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class ActionKind(StrEnum):
    immediate_mitigation = "immediate_mitigation"
    verification = "verification"
    durable_fix = "durable_fix"


class SuggestedAction(BaseModel):
    id: str = Field(default_factory=_id)
    kind: ActionKind
    title: str
    description: str
    command: str | None = None
    """Copyable shell/CLI command, when applicable. Display-only — never executed by the system."""


class Hypothesis(BaseModel):
    id: str = Field(default_factory=_id)
    rank: int
    summary: str
    reasoning: str
    confidence: Confidence
    evidence_ids: list[str]
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)


class InvestigationStatus(StrEnum):
    queued = "queued"
    triaging = "triaging"
    investigating = "investigating"
    synthesizing = "synthesizing"
    complete = "complete"
    needs_input = "needs_input"
    failed = "failed"


class InvestigationFeedback(BaseModel):
    hypothesis_id: str
    helpful: bool
    actual_root_cause: str | None = None
    created_at: datetime


class SubmitFeedbackRequest(BaseModel):
    """Body for POST /investigations/{id}/feedback. `created_at` is server-set on
    the resulting InvestigationFeedback — the client's clock isn't trustworthy and
    doesn't need to be."""
    hypothesis_id: str
    helpful: bool
    actual_root_cause: str | None = None


class Investigation(BaseModel):
    id: str = Field(default_factory=_id)
    alert: Alert
    status: InvestigationStatus = InvestigationStatus.queued
    tldr: str | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    feedback: list[InvestigationFeedback] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    """Deterministic correlation-guardrail caveats (see orchestrator/correlate.py) —
    independent of the model's own narrative, surfaced as a caveat in the UI."""
    created_at: datetime
    completed_at: datetime | None = None
    total_tool_calls: int = 0
    total_cost_usd: float = 0.0
    wall_time_ms: int | None = None
    error: str | None = None


class StreamEventType(StrEnum):
    step_started = "step_started"
    step_updated = "step_updated"
    step_finished = "step_finished"
    status_changed = "status_changed"
    investigation_complete = "investigation_complete"
    investigation_failed = "investigation_failed"


class StreamEvent(BaseModel):
    type: StreamEventType
    investigation_id: str
    payload: dict[str, object]


class CreateAlertRequest(BaseModel):
    """Body for POST /api/alerts. A raw-JSON alert (from a real webhook) supplies title/
    service/severity/message directly. A scenario-preset alert (from the 'Create Alert'
    UI) may supply only `scenario` — the server fills the rest in from the fixture's
    AlertTemplate, so the frontend never duplicates alert content that already lives in
    the fixtures. Any field given explicitly overrides the scenario's default.
    """
    title: str | None = None
    service: str | None = None
    severity: Severity | None = None
    message: str | None = None
    stack_trace: str | None = None
    fired_at: datetime | None = None
    source: AlertSource = AlertSource.manual
    scenario: str | None = None


class AskFollowUpRequest(BaseModel):
    question: str


class AskFollowUpResponse(BaseModel):
    answer: str
    cited_evidence_ids: list[str] = Field(default_factory=list)


class ScenarioSummary(BaseModel):
    key: str
    name: str
    description: str
    service: str
    severity: Severity
    """Preview of what the resulting alert will look like, for the Create Alert picker."""
    title: str
