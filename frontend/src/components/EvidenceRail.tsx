import { ExternalLink } from "lucide-react"
import { useMemo } from "react"
import { EVIDENCE_KIND_ICON } from "@/components/badges"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { formatClockTime } from "@/lib/format"
import type { Evidence, EvidenceKind } from "@/lib/types"
import { cn } from "@/lib/utils"

export type EvidenceGroup = "code" | "logs" | "metrics" | "topology"

const GROUP_KINDS: Record<EvidenceGroup, EvidenceKind[]> = {
  code: ["commit", "pull_request", "deploy", "code_owner"],
  logs: ["log", "error_group"],
  metrics: ["metric"],
  topology: ["service_map"],
}

const GROUP_LABEL: Record<EvidenceGroup, string> = {
  code: "Code & Deploys",
  logs: "Logs & Errors",
  metrics: "Metrics",
  topology: "Topology",
}

export function groupForEvidenceKind(kind: EvidenceKind): EvidenceGroup {
  return (Object.keys(GROUP_KINDS) as EvidenceGroup[]).find((g) => GROUP_KINDS[g].includes(kind))!
}

function EvidenceCard({ evidence, highlighted }: { evidence: Evidence; highlighted: boolean }) {
  const Icon = EVIDENCE_KIND_ICON[evidence.kind]
  return (
    <div
      id={`evidence-${evidence.id}`}
      className={cn(
        "rounded-lg border border-border bg-card p-2.5 transition-colors scroll-mt-4",
        highlighted && "border-primary/60 ring-1 ring-primary/40 bg-primary/5",
      )}
    >
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium leading-snug">{evidence.title}</p>
          <p className="mt-0.5 line-clamp-3 whitespace-pre-wrap font-mono text-[11px] text-muted-foreground">
            {evidence.summary}
          </p>
          <div className="mt-1 flex items-center justify-between">
            {evidence.occurred_at && (
              <span className="font-mono text-[10px] text-muted-foreground/70">
                {formatClockTime(evidence.occurred_at)}
              </span>
            )}
            {evidence.source_url && (
              <a
                href={evidence.source_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[10px] text-primary hover:underline"
              >
                source <ExternalLink className="size-2.5" />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export function EvidenceRail({
  evidence,
  highlightedId,
  tab,
  onTabChange,
}: {
  evidence: Evidence[]
  highlightedId: string | null
  tab: EvidenceGroup
  onTabChange: (group: EvidenceGroup) => void
}) {
  const byGroup = useMemo(() => {
    const map: Record<EvidenceGroup, Evidence[]> = { code: [], logs: [], metrics: [], topology: [] }
    for (const e of evidence) {
      map[groupForEvidenceKind(e.kind)].push(e)
    }
    for (const group of Object.keys(map) as EvidenceGroup[]) {
      map[group].sort((a, b) => (b.occurred_at ?? "").localeCompare(a.occurred_at ?? ""))
    }
    return map
  }, [evidence])

  if (evidence.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        No evidence gathered yet.
      </div>
    )
  }

  return (
    <Tabs
      value={tab}
      onValueChange={(v) => onTabChange(v as EvidenceGroup)}
      className="flex h-full flex-col gap-0"
    >
      <TabsList className="mx-2 mt-2">
        {(Object.keys(GROUP_KINDS) as EvidenceGroup[]).map((g) => (
          <TabsTrigger key={g} value={g} className="text-xs">
            {GROUP_LABEL[g]}
            {byGroup[g].length > 0 && (
              <span className="ml-1 text-muted-foreground">{byGroup[g].length}</span>
            )}
          </TabsTrigger>
        ))}
      </TabsList>
      {(Object.keys(GROUP_KINDS) as EvidenceGroup[]).map((g) => (
        <TabsContent key={g} value={g} className="min-h-0 flex-1">
          <ScrollArea className="h-full">
            <div className="space-y-2 p-2">
              {byGroup[g].length === 0 ? (
                <p className="p-4 text-center text-xs text-muted-foreground">Nothing here yet.</p>
              ) : (
                byGroup[g].map((e) => (
                  <EvidenceCard key={e.id} evidence={e} highlighted={e.id === highlightedId} />
                ))
              )}
            </div>
          </ScrollArea>
        </TabsContent>
      ))}
    </Tabs>
  )
}
