from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.fixtures.scenarios import SCENARIOS
from app.models.domain import (
    Alert,
    AskFollowUpRequest,
    AskFollowUpResponse,
    CreateAlertRequest,
    Investigation,
    InvestigationFeedback,
    InvestigationStatus,
    ScenarioSummary,
    Severity,
    SubmitFeedbackRequest,
)
from app.orchestrator.cli_agent import ClaudeCliError
from app.orchestrator.runner import NoActiveSessionError, ask_follow_up, run_investigation
from app.store import store

router = APIRouter()

_TERMINAL_STATUSES = {
    InvestigationStatus.complete,
    InvestigationStatus.failed,
    InvestigationStatus.needs_input,
}


@router.get("/scenarios", response_model=list[ScenarioSummary])
def list_scenarios() -> list[ScenarioSummary]:
    """Powers the 'Create Alert' preset picker — one entry per demo scenario, sourced
    directly from the fixtures so the UI can never drift from what's actually mocked."""
    return [
        ScenarioSummary(
            key=s.key,
            name=s.name,
            description=s.description,
            service=s.alert.service,
            severity=Severity(s.alert.severity),
            title=s.alert.title,
        )
        for s in SCENARIOS.values()
    ]


@router.post("/alerts", response_model=Investigation)
async def create_alert(req: CreateAlertRequest, background_tasks: BackgroundTasks) -> Investigation:
    """Single ingress path for both the webhook and the 'Create Alert' UI button —
    both post this exact shape. A preset click can send just `{"scenario": "..."}`;
    a raw webhook must send title/service/severity/message directly.
    """
    if req.scenario and req.scenario not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown scenario '{req.scenario}'")
    template = SCENARIOS[req.scenario].alert if req.scenario else None
    if template is None and not (req.title and req.service and req.severity and req.message):
        raise HTTPException(
            status_code=422,
            detail="Either `scenario`, or title+service+severity+message, must be provided.",
        )

    severity = req.severity or (Severity(template.severity) if template else None)
    assert severity is not None  # guaranteed by the validation above
    alert = Alert(
        title=req.title or (template.title if template else ""),
        service=req.service or (template.service if template else ""),
        severity=severity,
        message=req.message or (template.message if template else ""),
        stack_trace=req.stack_trace or (template.stack_trace if template else None),
        fired_at=req.fired_at or datetime.now(UTC),
        source=req.source,
        scenario=req.scenario,
    )
    investigation = Investigation(alert=alert, created_at=datetime.now(UTC))
    store.create(investigation)
    background_tasks.add_task(run_investigation, investigation.id)
    return investigation


@router.get("/investigations", response_model=list[Investigation])
def list_investigations() -> list[Investigation]:
    return store.list()


@router.get("/investigations/{investigation_id}", response_model=Investigation)
def get_investigation(investigation_id: str) -> Investigation:
    investigation = store.get(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation


@router.get("/investigations/{investigation_id}/stream")
async def stream_investigation(investigation_id: str) -> EventSourceResponse:
    investigation = store.get(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    queue = store.subscribe(investigation_id)

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        try:
            # Replay current state first so a late-connecting client isn't lost.
            yield {"event": "snapshot", "data": json.dumps(investigation.model_dump(mode="json"))}
            if investigation.status in _TERMINAL_STATUSES:
                # Already finished by the time the client subscribed — nothing will
                # ever be published for it again, so don't hold the connection open
                # pinging every 30s until the client eventually gives up.
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"event": str(event["type"]), "data": json.dumps(event)}
                if event["type"] in ("investigation_complete", "investigation_failed"):
                    break
        finally:
            store.unsubscribe(investigation_id, queue)

    return EventSourceResponse(event_generator())


@router.post("/investigations/{investigation_id}/feedback", response_model=Investigation)
def submit_feedback(investigation_id: str, req: SubmitFeedbackRequest) -> Investigation:
    investigation = store.get(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if not any(h.id == req.hypothesis_id for h in investigation.hypotheses):
        raise HTTPException(
            status_code=404, detail=f"No hypothesis '{req.hypothesis_id}' on this investigation"
        )
    investigation.feedback.append(
        InvestigationFeedback(
            hypothesis_id=req.hypothesis_id,
            helpful=req.helpful,
            actual_root_cause=req.actual_root_cause,
            created_at=datetime.now(UTC),
        )
    )
    store.update(investigation)
    return investigation


@router.post("/investigations/{investigation_id}/ask", response_model=AskFollowUpResponse)
async def ask_follow_up_route(
    investigation_id: str, req: AskFollowUpRequest
) -> AskFollowUpResponse:
    investigation = store.get(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    try:
        result = await ask_follow_up(investigation, req.question)
    except NoActiveSessionError as e:
        raise HTTPException(
            status_code=409,
            detail=(
                "This investigation has no resumable session — it may be from a previous "
                "backend process, or it failed before an agent session was created."
            ),
        ) from e
    except ClaudeCliError as e:
        raise HTTPException(
            status_code=502, detail=f"The follow-up call to the agent failed: {e}"
        ) from e
    return AskFollowUpResponse(**result)
