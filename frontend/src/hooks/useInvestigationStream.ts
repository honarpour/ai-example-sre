import { useEffect, useRef, useState } from "react"
import { api, ApiError } from "@/lib/api"
import { getSavedInvestigation, saveInvestigation } from "@/lib/db"
import type { AgentStep, Evidence, Investigation } from "@/lib/types"

interface StepEventPayload {
  step: AgentStep
  new_evidence: Evidence[]
}

function upsertStep(steps: AgentStep[], step: AgentStep): AgentStep[] {
  const idx = steps.findIndex((s) => s.id === step.id)
  if (idx === -1) return [...steps, step]
  const copy = steps.slice()
  copy[idx] = step
  return copy
}

function mergeEvidence(existing: Evidence[], incoming: Evidence[]): Evidence[] {
  if (incoming.length === 0) return existing
  const known = new Set(existing.map((e) => e.id))
  const fresh = incoming.filter((e) => !known.has(e.id))
  return fresh.length ? [...existing, ...fresh] : existing
}

const TERMINAL_STATUSES = new Set(["complete", "failed", "needs_input"])
const isTerminal = (status: string | undefined) => !!status && TERMINAL_STATUSES.has(status)

/** Drives a single investigation's live state. A finished investigation from a
 * prior backend process (dev server restart, or just a while since it ran) has
 * no live process to stream from — the backend's in-memory store won't even
 * know the id — so this checks IndexedDB and a plain GET before ever opening
 * SSE, and only streams when the investigation is actually still in flight. */
export function useInvestigationStream(investigationId: string | undefined) {
  const [investigation, setInvestigation] = useState<Investigation | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [notFound, setNotFound] = useState(false)
  const savedRef = useRef(false)

  useEffect(() => {
    if (!investigationId) return
    setInvestigation(null)
    setConnectionError(null)
    setNotFound(false)
    savedRef.current = false

    let cancelled = false
    let source: EventSource | null = null

    const startStreaming = () => {
      source = new EventSource(api.streamUrl(investigationId))

      source.addEventListener("snapshot", (e: MessageEvent) => {
        const snapshot: Investigation = JSON.parse(e.data)
        setInvestigation(snapshot)
        if (isTerminal(snapshot.status)) source?.close()
      })

      for (const type of ["step_started", "step_finished"] as const) {
        source.addEventListener(type, (e: MessageEvent) => {
          const { payload } = JSON.parse(e.data) as { payload: StepEventPayload }
          setInvestigation((prev) =>
            prev
              ? {
                  ...prev,
                  steps: upsertStep(prev.steps, payload.step),
                  evidence: mergeEvidence(prev.evidence, payload.new_evidence),
                }
              : prev,
          )
        })
      }

      source.addEventListener("status_changed", (e: MessageEvent) => {
        const { payload } = JSON.parse(e.data) as { payload: { status: Investigation["status"] } }
        setInvestigation((prev) => (prev ? { ...prev, status: payload.status } : prev))
      })

      for (const type of ["investigation_complete", "investigation_failed"] as const) {
        source.addEventListener(type, (e: MessageEvent) => {
          const { payload } = JSON.parse(e.data) as { payload: Investigation }
          setInvestigation(payload)
          if (!savedRef.current) {
            savedRef.current = true
            void saveInvestigation(payload)
          }
          source?.close()
        })
      }

      source.onerror = () => {
        if (source?.readyState === EventSource.CLOSED) {
          setConnectionError("Connection to the investigation stream was lost.")
        }
      }
    }

    void (async () => {
      const local = await getSavedInvestigation(investigationId)
      if (local && isTerminal(local.status)) {
        if (!cancelled) setInvestigation(local)
        return
      }

      try {
        const server = await api.getInvestigation(investigationId)
        if (cancelled) return
        setInvestigation(server)
        if (isTerminal(server.status)) {
          void saveInvestigation(server)
        } else {
          startStreaming()
        }
      } catch (e) {
        if (cancelled) return
        if (local) {
          setInvestigation(local)
        } else if (e instanceof ApiError && e.status === 404) {
          setNotFound(true)
        } else {
          setConnectionError("Couldn't reach the backend for this investigation.")
        }
      }
    })()

    return () => {
      cancelled = true
      source?.close()
    }
  }, [investigationId])

  return { investigation, connectionError, notFound }
}
