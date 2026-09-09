import { ArrowLeft, ListTree, Loader2, RotateCcw } from "lucide-react"
import { useEffect, useState } from "react"
import { SeverityBadge, StatusBadge } from "@/components/badges"
import { AgentTimeline } from "@/components/AgentTimeline"
import { CostFooter } from "@/components/CostFooter"
import { type EvidenceGroup, EvidenceRail, groupForEvidenceKind } from "@/components/EvidenceRail"
import { IncidentTimelineStrip } from "@/components/IncidentTimelineStrip"
import { ShareButtons } from "@/components/ShareButtons"
import { Button } from "@/components/ui/button"
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { VerdictPanel } from "@/components/VerdictPanel"
import { useInvestigationStream } from "@/hooks/useInvestigationStream"
import { api, ApiError } from "@/lib/api"
import type { Investigation } from "@/lib/types"

const TERMINAL_STATUSES = new Set(["complete", "failed", "needs_input"])

export function InvestigationView({
  investigationId,
  onBack,
  onRerun,
}: {
  investigationId: string
  onBack: () => void
  onRerun: (investigation: Investigation) => void
}) {
  const { investigation, connectionError, notFound } = useInvestigationStream(investigationId)
  const [evidenceTab, setEvidenceTab] = useState<EvidenceGroup>("code")
  // A nonce alongside the id, not just the id, so re-clicking the SAME citation
  // chip while its highlight is still active re-triggers the scroll+highlight
  // instead of silently doing nothing (setState with an unchanged id wouldn't
  // re-run the effect below).
  const [highlighted, setHighlighted] = useState<{ id: string; nonce: number } | null>(null)
  const [rerunning, setRerunning] = useState(false)
  const [rerunError, setRerunError] = useState<string | null>(null)

  useEffect(() => {
    if (!highlighted) return
    const el = document.getElementById(`evidence-${highlighted.id}`)
    el?.scrollIntoView({ behavior: "smooth", block: "center" })
    const timeout = setTimeout(() => setHighlighted(null), 2200)
    return () => clearTimeout(timeout)
  }, [highlighted])

  if (notFound) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <p className="text-sm font-medium">Investigation not found</p>
        <p className="max-w-sm text-xs text-muted-foreground">
          It isn't in this backend's memory or your browser's saved history — it may be from a
          different session.
        </p>
        <button type="button" onClick={onBack} className="mt-2 text-xs text-primary hover:underline">
          Back to inbox
        </button>
      </div>
    )
  }

  if (!investigation) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading investigation...
      </div>
    )
  }

  const onCiteEvidence = (id: string) => {
    const evidence = investigation.evidence.find((e) => e.id === id)
    if (!evidence) return
    setEvidenceTab(groupForEvidenceKind(evidence.kind))
    // Switching tabs unmounts the previous panel's content; wait a tick so the
    // target evidence card actually exists before we try to scroll to it.
    requestAnimationFrame(() =>
      setHighlighted((prev) => ({ id, nonce: (prev?.nonce ?? 0) + 1 })),
    )
  }

  const rerun = async () => {
    if (!investigation.alert.scenario) return
    setRerunning(true)
    setRerunError(null)
    try {
      const fresh = await api.createAlert({
        scenario: investigation.alert.scenario,
        source: "manual",
      })
      onRerun(fresh)
    } catch (e) {
      setRerunError(e instanceof ApiError ? e.message : "Failed to start a new investigation.")
    } finally {
      setRerunning(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border px-4 py-3">
        <button
          type="button"
          onClick={onBack}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
          aria-label="Back to inbox"
        >
          <ArrowLeft className="size-4" />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-sm font-semibold">{investigation.alert.title}</h1>
            <SeverityBadge severity={investigation.alert.severity} />
          </div>
          <p className="font-mono text-xs text-muted-foreground">{investigation.alert.service}</p>
        </div>
        <ShareButtons investigation={investigation} />
        {investigation.alert.scenario && TERMINAL_STATUSES.has(investigation.status!) && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="size-7" onClick={rerun} disabled={rerunning}>
                {rerunning ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>Run a fresh investigation of this same alert</TooltipContent>
          </Tooltip>
        )}
        <StatusBadge status={investigation.status!} />
      </header>

      {(connectionError || rerunError) && (
        <div className="border-b border-warning/30 bg-warning/10 px-4 py-1.5 text-xs text-foreground/90">
          {connectionError || rerunError}
        </div>
      )}

      <IncidentTimelineStrip investigation={investigation} />

      {/* min-w-0 lets this row shrink inside its flex parent so overflow-x-auto below
          can actually kick in, instead of the row forcing the whole page wider. Panel
          sizes persist per-browser via autoSaveId (localStorage) so a resize sticks
          across reloads and future investigations, not just this one render. */}
      <div className="min-h-0 min-w-0 flex-1 overflow-x-auto">
        <ResizablePanelGroup
          direction="horizontal"
          autoSaveId="investigation-view-panels"
          className="h-full min-w-[860px]"
        >
          <ResizablePanel id="timeline" order={1} defaultSize={22} minSize={15} maxSize={40}>
            <section className="flex h-full min-h-0 flex-col">
              <div className="flex items-center gap-1.5 border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
                <ListTree className="size-3.5" />
                Agent timeline
              </div>
              <ScrollArea horizontal className="min-h-0 flex-1">
                <AgentTimeline steps={investigation.steps} />
              </ScrollArea>
            </section>
          </ResizablePanel>

          <ResizableHandle withHandle />

          <ResizablePanel id="verdict" order={2} defaultSize={48} minSize={30}>
            <section className="h-full min-h-0 overflow-y-auto">
              <VerdictPanel investigation={investigation} onCiteEvidence={onCiteEvidence} />
            </section>
          </ResizablePanel>

          <ResizableHandle withHandle />

          <ResizablePanel id="evidence" order={3} defaultSize={30} minSize={18} maxSize={45}>
            <section className="h-full min-h-0">
              <EvidenceRail
                evidence={investigation.evidence}
                highlightedId={highlighted?.id ?? null}
                tab={evidenceTab}
                onTabChange={setEvidenceTab}
              />
            </section>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>

      <CostFooter investigation={investigation} />
    </div>
  )
}
