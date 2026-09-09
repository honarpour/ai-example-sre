import { AlertTriangle } from "lucide-react"
import { useMemo } from "react"
import { EVIDENCE_KIND_ICON } from "@/components/badges"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatClockTime } from "@/lib/format"
import type { Evidence, Investigation } from "@/lib/types"
import { cn } from "@/lib/utils"

const TIMELINE_KINDS = new Set(["deploy", "pull_request", "error_group"])

interface TimelineMarker {
  id: string
  time: number
  label: string
  detail: string
  kind: "alert" | Evidence["kind"]
  correlated: boolean
}

/** The single highest-value visual for an on-call engineer: everything that
 * happened around the alert, in one chronological glance, before reading a
 * word of the writeup. Time-scaled, not just a list — a slow-building
 * incident (resource-leak, hours-wide) and a sudden one (bad-deploy,
 * minutes-wide) should visually read as different shapes. */
export function IncidentTimelineStrip({ investigation }: { investigation: Investigation }) {
  const markers = useMemo<TimelineMarker[]>(() => {
    const fromEvidence: TimelineMarker[] = investigation.evidence
      .filter((e) => e.occurred_at && (TIMELINE_KINDS.has(e.kind) || e.summary.includes("[audit]")))
      .map((e) => ({
        id: e.id!,
        time: new Date(e.occurred_at!).getTime(),
        label: e.title,
        detail: e.summary,
        kind: e.kind,
        correlated: investigation.hypotheses.some((h) => h.evidence_ids.includes(e.id!)),
      }))

    const alertMarker: TimelineMarker = {
      id: "alert",
      time: new Date(investigation.alert.fired_at).getTime(),
      label: "Alert fired",
      detail: investigation.alert.title,
      kind: "alert",
      correlated: false,
    }

    return [...fromEvidence, alertMarker].sort((a, b) => a.time - b.time)
  }, [investigation])

  if (markers.length <= 1) return null

  const times = markers.map((m) => m.time)
  const rawMin = Math.min(...times)
  const rawMax = Math.max(...times)
  const span = Math.max(rawMax - rawMin, 60_000)
  const pad = span * 0.08
  const min = rawMin - pad
  const max = rawMax + pad

  const pct = (t: number) => ((t - min) / (max - min)) * 100

  return (
    <div className="border-b border-border bg-card/50 px-4 py-3">
      <div className="mb-2 flex items-center justify-between text-[10px] text-muted-foreground">
        <span>{formatClockTime(new Date(min).toISOString())}</span>
        <span className="font-medium">Incident timeline</span>
        <span>{formatClockTime(new Date(max).toISOString())}</span>
      </div>
      <div className="relative h-8">
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border" />
        {markers.map((m) => (
          <Tooltip key={m.id}>
            <TooltipTrigger asChild>
              <button
                type="button"
                style={{ left: `${pct(m.time)}%` }}
                className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full p-0.5 transition-transform hover:scale-125 focus-visible:scale-125 focus-visible:outline-none"
              >
                <MarkerDot marker={m} />
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">
              <p className="font-medium">{m.label}</p>
              <p className="text-muted-foreground">{m.detail}</p>
              <p className="mt-1 font-mono text-[10px]">{formatClockTime(new Date(m.time).toISOString())}</p>
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
    </div>
  )
}

function MarkerDot({ marker }: { marker: TimelineMarker }) {
  if (marker.kind === "alert") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-destructive text-destructive-foreground shadow-sm ring-2 ring-background">
        <AlertTriangle className="size-3" />
      </span>
    )
  }
  const Icon = EVIDENCE_KIND_ICON[marker.kind]
  return (
    <span
      className={cn(
        "flex size-4 items-center justify-center rounded-full shadow-sm ring-2 ring-background",
        marker.correlated ? "bg-primary text-primary-foreground" : "bg-muted-foreground/40 text-background",
      )}
    >
      <Icon className="size-2.5" />
    </span>
  )
}
