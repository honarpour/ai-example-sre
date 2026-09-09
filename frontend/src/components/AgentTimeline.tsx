import { AlertCircle, ChevronDown, ChevronRight, Loader2, MessageSquare, Wrench } from "lucide-react"
import { useState } from "react"
import { formatClockTime } from "@/lib/format"
import type { AgentStep } from "@/lib/types"
import { cn } from "@/lib/utils"

function StepIcon({ step }: { step: AgentStep }) {
  if (step.status === "running") return <Loader2 className="size-3.5 animate-spin text-primary" />
  if (step.status === "error") return <AlertCircle className="size-3.5 text-destructive" />
  if (!step.tool_name) return <MessageSquare className="size-3.5 text-muted-foreground" />
  return <Wrench className="size-3.5 text-success" />
}

function ToolStep({ step }: { step: AgentStep }) {
  const [expanded, setExpanded] = useState(false)
  const hasDetail = Boolean(step.tool_input || step.tool_output_summary || step.error)

  return (
    <div className="group">
      <button
        type="button"
        disabled={!hasDetail}
        onClick={() => setExpanded((v) => !v)}
        className="flex w-max min-w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-accent/40 disabled:hover:bg-transparent"
      >
        {/* Chevron, icon, and timestamp are all fixed at the row's left edge, in that
            order, and never move — only the label after them grows/scrolls. Previously
            the timestamp used ml-auto to sit at the row's end, which meant a short label
            left a large empty gap before it, and a long label pushed it (and the
            expand chevron) off-screen until scrolled all the way over — hiding actual
            data (the time) behind a UI affordance, not just a cosmetic issue. */}
        <span className="mt-0.5 shrink-0">
          {hasDetail ? (
            expanded ? (
              <ChevronDown className="size-3 text-muted-foreground" />
            ) : (
              <ChevronRight className="size-3 text-muted-foreground" />
            )
          ) : (
            <span className="block size-3" />
          )}
        </span>
        <span className="mt-0.5 shrink-0">
          <StepIcon step={step} />
        </span>
        <span className="shrink-0 whitespace-nowrap font-mono text-[10px] tabular-nums text-muted-foreground/70">
          {formatClockTime(step.started_at)}
        </span>
        {/* Deliberately not truncated: a tool call's full arguments (long file paths,
            multiple kwargs) were previously clipped with an ellipsis and no way to see
            the rest. whitespace-nowrap lets this grow past the row's width instead, and
            the panel's horizontal scrollbar (see InvestigationView.tsx) reaches it. */}
        <span className="shrink-0 whitespace-nowrap font-mono text-xs text-foreground/90">
          {step.label}
        </span>
      </button>
      {expanded && (
        <div className="ml-6 mb-1 space-y-1.5 rounded-md border border-border bg-muted/30 p-2 font-mono text-[11px]">
          {step.tool_input && Object.keys(step.tool_input).length > 0 && (
            <div>
              <span className="text-muted-foreground">input: </span>
              <span className="break-all text-foreground/80">{JSON.stringify(step.tool_input)}</span>
            </div>
          )}
          {step.tool_output_summary && (
            <div>
              <span className="text-muted-foreground">output: </span>
              <span className="break-all text-foreground/80">{step.tool_output_summary}</span>
            </div>
          )}
          {step.error && <div className="text-destructive break-all">error: {step.error}</div>}
        </div>
      )}
    </div>
  )
}

function NarrationStep({ step }: { step: AgentStep }) {
  return (
    <div className="flex items-start gap-2 px-2 py-1.5">
      <span className="mt-0.5 shrink-0">
        <StepIcon step={step} />
      </span>
      <span className="text-xs italic text-muted-foreground">{step.label}</span>
    </div>
  )
}

export function AgentTimeline({ steps }: { steps: AgentStep[] }) {
  if (steps.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        Waiting for the investigation to start...
      </div>
    )
  }

  return (
    <div className={cn("min-w-max space-y-0.5 py-2")}>
      {steps.map((step) =>
        step.tool_name ? <ToolStep key={step.id} step={step} /> : <NarrationStep key={step.id} step={step} />,
      )}
    </div>
  )
}
