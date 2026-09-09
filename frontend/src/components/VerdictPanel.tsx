import { AlertTriangle, FlaskConical, Sparkles, TerminalSquare } from "lucide-react"
import { useState } from "react"
import { ACTION_KIND_CONFIG, ConfidenceBadge, EVIDENCE_KIND_ICON } from "@/components/badges"
import { CopyButton } from "@/components/CopyButton"
import { FeedbackButtons } from "@/components/FeedbackButtons"
import { FollowUpPanel } from "@/components/FollowUpPanel"
import { Button } from "@/components/ui/button"
import type { Evidence, Hypothesis, Investigation } from "@/lib/types"
import { cn } from "@/lib/utils"

const TERMINAL_STATUSES = new Set(["complete", "failed", "needs_input"])

/** "One simulated action" per PLAN.md Phase 4 — shows exactly what a real
 * mitigation command would do, with an explicit, impossible-to-miss label that
 * nothing was actually executed. Demonstrates the shape of human-in-the-loop
 * action-taking without needing a real permissions/execution story. */
function SimulateAction({ command }: { command: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-1">
      <Button
        variant="outline"
        size="sm"
        className="h-6 gap-1 px-2 text-[11px]"
        onClick={() => setOpen((v) => !v)}
      >
        <FlaskConical className="size-3" />
        {open ? "Hide simulation" : "Simulate"}
      </Button>
      {open && (
        <div className="mt-1.5 rounded-md border border-warning/30 bg-warning/5 p-2">
          <div className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-warning">
            <TerminalSquare className="size-3" />
            Simulation — not executed
          </div>
          <code className="mt-1 block whitespace-pre-wrap font-mono text-[11px] text-foreground/80">
            $ {command}
          </code>
          <p className="mt-1 text-[10px] text-muted-foreground">
            This is a preview only. A production version would require explicit approval and a
            real execution path before ever running a command like this.
          </p>
        </div>
      )}
    </div>
  )
}

function EvidenceChip({
  evidence,
  onClick,
}: {
  evidence: Evidence | undefined
  onClick: () => void
}) {
  if (!evidence) return null
  const Icon = EVIDENCE_KIND_ICON[evidence.kind]
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex max-w-[220px] items-center gap-1 rounded-full border border-border bg-muted/50 px-2 py-0.5 text-[11px] text-foreground/80 transition-colors hover:border-primary/50 hover:bg-accent/60"
      title={evidence.title}
    >
      <Icon className="size-2.5 shrink-0" />
      <span className="truncate">{evidence.title}</span>
    </button>
  )
}

function HypothesisCard({
  investigationId,
  hypothesis,
  evidenceById,
  onCiteEvidence,
}: {
  investigationId: string
  hypothesis: Hypothesis
  evidenceById: Map<string, Evidence>
  onCiteEvidence: (id: string) => void
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        hypothesis.rank === 1 ? "border-primary/40 bg-primary/[0.04]" : "border-border bg-card",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          {hypothesis.rank === 1 ? "Leading hypothesis" : `Hypothesis #${hypothesis.rank}`}
        </span>
        <ConfidenceBadge confidence={hypothesis.confidence} />
      </div>

      <p className="mt-2 text-sm font-medium leading-snug">{hypothesis.summary}</p>
      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{hypothesis.reasoning}</p>

      {hypothesis.evidence_ids.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {hypothesis.evidence_ids.map((id) => (
            <EvidenceChip key={id} evidence={evidenceById.get(id)} onClick={() => onCiteEvidence(id)} />
          ))}
        </div>
      )}

      {hypothesis.suggested_actions.length > 0 && (
        <div className="mt-3 space-y-1.5 border-t border-border pt-3">
          {hypothesis.suggested_actions.map((action) => {
            const cfg = ACTION_KIND_CONFIG[action.kind]
            const Icon = cfg.icon
            return (
              <div key={action.id} className="flex items-start gap-2">
                <Icon className={cn("mt-0.5 size-3.5 shrink-0", cfg.className)} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium">{action.title}</span>
                    <span className={cn("text-[10px] uppercase tracking-wide", cfg.className)}>
                      {cfg.label}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">{action.description}</p>
                  {action.command && (
                    <>
                      <div className="mt-1 flex items-center gap-1 rounded-md bg-muted/60 px-2 py-1">
                        <code className="flex-1 truncate font-mono text-[11px]">{action.command}</code>
                        <CopyButton text={action.command} />
                      </div>
                      <SimulateAction command={action.command} />
                    </>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div className="mt-3 border-t border-border pt-2.5">
        <FeedbackButtons investigationId={investigationId} hypothesisId={hypothesis.id!} />
      </div>
    </div>
  )
}

export function VerdictPanel({
  investigation,
  onCiteEvidence,
}: {
  investigation: Investigation
  onCiteEvidence: (id: string) => void
}) {
  const evidenceById = new Map(investigation.evidence.map((e) => [e.id!, e]))
  const inProgress = !TERMINAL_STATUSES.has(investigation.status!)

  if (inProgress && investigation.hypotheses.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
        <Sparkles className="size-6 animate-pulse-dot text-primary" />
        <p className="text-sm text-muted-foreground">Investigating — findings will appear here.</p>
      </div>
    )
  }

  if (investigation.status === "failed") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
        <AlertTriangle className="size-6 text-destructive" />
        <p className="text-sm font-medium">Investigation failed</p>
        <p className="max-w-sm text-xs text-muted-foreground">{investigation.error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4 p-4">
      {investigation.tldr && (
        <div className="rounded-xl border border-border bg-card p-4">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            TL;DR
          </span>
          <p className="mt-1.5 text-sm leading-relaxed">{investigation.tldr}</p>
        </div>
      )}

      {investigation.warnings.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          <div className="space-y-1">
            {investigation.warnings.map((w) => (
              <p key={w} className="text-xs text-foreground/90">
                {w}
              </p>
            ))}
          </div>
        </div>
      )}

      {investigation.status === "needs_input" && (
        <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          <p className="text-xs text-foreground/90">
            Automated synthesis didn't complete — review the raw evidence on the right.
          </p>
        </div>
      )}

      <div className="space-y-3">
        {investigation.hypotheses.map((h) => (
          <HypothesisCard
            key={h.id}
            investigationId={investigation.id!}
            hypothesis={h}
            evidenceById={evidenceById}
            onCiteEvidence={onCiteEvidence}
          />
        ))}
      </div>

      <FollowUpPanel
        investigationId={investigation.id!}
        evidence={investigation.evidence}
        disabled={!TERMINAL_STATUSES.has(investigation.status!)}
        onCiteEvidence={onCiteEvidence}
      />
    </div>
  )
}
