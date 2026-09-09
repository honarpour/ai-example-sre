"""In-memory investigation store. This is the backend's source of truth during a run;
the frontend mirrors completed investigations into IndexedDB for reload-durable history.
No database — see PLAN.md decision #6.
"""
from __future__ import annotations

import asyncio

from app.models.domain import Investigation


class InvestigationStore:
    def __init__(self) -> None:
        self._investigations: dict[str, Investigation] = {}
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, object]]]] = {}
        self._sessions: dict[str, str] = {}

    def create(self, investigation: Investigation) -> None:
        self._investigations[investigation.id] = investigation
        self._subscribers[investigation.id] = []

    def set_session(self, investigation_id: str, session_id: str) -> None:
        """Tracks the `claude` CLI session id backing an investigation, so a later
        follow-up question (see /investigations/{id}/ask) can `--resume` the same
        conversation instead of starting cold. Server-memory only — an investigation
        loaded from a browser's IndexedDB after a backend restart has no session to
        resume, and the ask endpoint reports that plainly rather than guessing."""
        self._sessions[investigation_id] = session_id

    def get_session(self, investigation_id: str) -> str | None:
        return self._sessions.get(investigation_id)

    def get(self, investigation_id: str) -> Investigation | None:
        return self._investigations.get(investigation_id)

    def list(self) -> list[Investigation]:
        return sorted(self._investigations.values(), key=lambda i: i.created_at, reverse=True)

    def update(self, investigation: Investigation) -> None:
        self._investigations[investigation.id] = investigation

    def subscribe(self, investigation_id: str) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue[dict[str, object]]()
        self._subscribers.setdefault(investigation_id, []).append(queue)
        return queue

    def unsubscribe(self, investigation_id: str, queue: asyncio.Queue[dict[str, object]]) -> None:
        subs = self._subscribers.get(investigation_id, [])
        if queue in subs:
            subs.remove(queue)

    async def publish(self, investigation_id: str, event: dict[str, object]) -> None:
        for queue in self._subscribers.get(investigation_id, []):
            await queue.put(event)


store = InvestigationStore()
