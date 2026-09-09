import { useCallback, useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import { listSavedInvestigations, saveInvestigation } from "@/lib/db"
import type { Investigation } from "@/lib/types"

const TERMINAL_STATUSES = new Set(["complete", "failed", "needs_input"])
const POLL_INTERVAL_MS = 4000

function mergeById(server: Investigation[], local: Investigation[]): Investigation[] {
  const byId = new Map<string, Investigation>()
  for (const inv of local) byId.set(inv.id!, inv)
  for (const inv of server) byId.set(inv.id!, inv) // server wins — it's the live source of truth
  return [...byId.values()].sort((a, b) => {
    // A comparator that never returns 0 for equal timestamps is inconsistent
    // (compare(a,b) and compare(b,a) can BOTH claim "goes first"), which showed
    // up as inbox rows visibly swapping position on every poll. `id` breaks
    // ties deterministically instead.
    if (a.created_at! !== b.created_at!) return a.created_at! < b.created_at! ? 1 : -1
    return a.id! < b.id! ? 1 : a.id! > b.id! ? -1 : 0
  })
}

/** Powers the alerts inbox: server list is authoritative for anything from this
 * backend process's lifetime; IndexedDB fills in history from before a backend
 * restart (there's no database — see PLAN.md decision #6). Polls lightly only
 * while something is still in flight, so an idle inbox costs nothing. */
export function useInvestigations() {
  const [investigations, setInvestigations] = useState<Investigation[]>([])
  const [loading, setLoading] = useState(true)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    const [server, local] = await Promise.all([
      api.listInvestigations().catch(() => []),
      listSavedInvestigations(),
    ])
    const merged = mergeById(server, local)
    setInvestigations(merged)
    for (const inv of server) {
      if (inv.status && TERMINAL_STATUSES.has(inv.status)) void saveInvestigation(inv)
    }
    return merged
  }, [])

  useEffect(() => {
    let cancelled = false
    void refresh().finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [refresh])

  useEffect(() => {
    const hasInFlight = investigations.some(
      (inv) => !inv.status || !TERMINAL_STATUSES.has(inv.status),
    )
    if (pollRef.current) clearInterval(pollRef.current)
    if (hasInFlight) {
      pollRef.current = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [investigations, refresh])

  const addOptimistic = useCallback((investigation: Investigation) => {
    setInvestigations((prev) => [investigation, ...prev])
  }, [])

  return { investigations, loading, refresh, addOptimistic }
}
