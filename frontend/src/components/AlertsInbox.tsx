import { Inbox } from "lucide-react"
import { SeverityBadge, StatusBadge } from "@/components/badges"
import { Skeleton } from "@/components/ui/skeleton"
import { formatRelativeTime } from "@/lib/format"
import type { Investigation } from "@/lib/types"
import { cn } from "@/lib/utils"

const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }

export function AlertsInbox({
  investigations,
  loading,
  selectedId,
  onSelect,
}: {
  investigations: Investigation[]
  loading: boolean
  selectedId: string | undefined
  onSelect: (id: string) => void
}) {
  if (loading) {
    return (
      <div className="space-y-2 p-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-16 w-full rounded-lg" />
        ))}
      </div>
    )
  }

  if (investigations.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted-foreground">
        <Inbox className="size-8 opacity-50" />
        <p className="text-sm">No alerts yet.</p>
        <p className="text-xs">Create one to start an investigation.</p>
      </div>
    )
  }

  const sorted = [...investigations].sort((a, b) => {
    const aOngoing = a.status !== "complete" && a.status !== "failed" && a.status !== "needs_input"
    const bOngoing = b.status !== "complete" && b.status !== "failed" && b.status !== "needs_input"
    if (aOngoing !== bOngoing) return aOngoing ? -1 : 1
    const sevDiff = (SEVERITY_ORDER[a.alert.severity] ?? 9) - (SEVERITY_ORDER[b.alert.severity] ?? 9)
    if (aOngoing && sevDiff !== 0) return sevDiff
    return a.created_at! < b.created_at! ? 1 : -1
  })

  return (
    <ul className="divide-y divide-border" role="list" aria-label="Alerts">
      {sorted.map((inv) => (
        <li key={inv.id}>
          <button
            type="button"
            onClick={() => onSelect(inv.id!)}
            className={cn(
              "w-full text-left px-3 py-3 transition-colors hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none",
              selectedId === inv.id && "bg-accent/70",
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-medium leading-tight">{inv.alert.title}</span>
              <SeverityBadge severity={inv.alert.severity} className="shrink-0" />
            </div>
            <div className="mt-1 flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-muted-foreground">{inv.alert.service}</span>
              <span className="text-xs text-muted-foreground">{formatRelativeTime(inv.created_at!)}</span>
            </div>
            <div className="mt-1.5">
              <StatusBadge status={inv.status!} />
            </div>
          </button>
        </li>
      ))}
    </ul>
  )
}
