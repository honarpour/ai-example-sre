import { cn } from "@/lib/utils"
import type { ActionKind, Confidence, EvidenceKind, InvestigationStatus, Severity } from "@/lib/types"
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Clock,
  GitCommit,
  GitPullRequest,
  Info,
  Loader2,
  type LucideIcon,
  Network,
  Rocket,
  ScrollText,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Users,
  Wrench,
  XCircle,
} from "lucide-react"

const SEVERITY_STYLES: Record<Severity, string> = {
  critical: "bg-sev-critical/15 text-sev-critical border-sev-critical/30",
  high: "bg-sev-high/15 text-sev-high border-sev-high/30",
  medium: "bg-sev-medium/15 text-sev-medium border-sev-medium/30",
  low: "bg-sev-low/15 text-sev-low border-sev-low/30",
}

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide",
        SEVERITY_STYLES[severity],
        className,
      )}
    >
      {severity}
    </span>
  )
}

const CONFIDENCE_STYLES: Record<Confidence, string> = {
  high: "bg-conf-high/15 text-conf-high border-conf-high/30",
  medium: "bg-conf-medium/15 text-conf-medium border-conf-medium/30",
  low: "bg-conf-low/15 text-conf-low border-conf-low/30",
}

const CONFIDENCE_ICON: Record<Confidence, LucideIcon> = {
  high: ShieldCheck,
  medium: Shield,
  low: ShieldQuestion,
}

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const Icon = CONFIDENCE_ICON[confidence]
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide",
        CONFIDENCE_STYLES[confidence],
      )}
    >
      <Icon className="size-3" />
      {confidence} confidence
    </span>
  )
}

const STATUS_CONFIG: Record<
  InvestigationStatus,
  { label: string; icon: LucideIcon; className: string; spin?: boolean }
> = {
  queued: { label: "Queued", icon: CircleDashed, className: "text-muted-foreground" },
  triaging: { label: "Triaging", icon: Loader2, className: "text-primary", spin: true },
  investigating: { label: "Investigating", icon: Loader2, className: "text-primary", spin: true },
  synthesizing: { label: "Synthesizing", icon: Loader2, className: "text-primary", spin: true },
  complete: { label: "Complete", icon: CheckCircle2, className: "text-success" },
  needs_input: { label: "Needs review", icon: AlertTriangle, className: "text-warning" },
  failed: { label: "Failed", icon: XCircle, className: "text-destructive" },
}

export function StatusBadge({ status, className }: { status: InvestigationStatus; className?: string }) {
  const cfg = STATUS_CONFIG[status]
  const Icon = cfg.icon
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", cfg.className, className)}>
      <Icon className={cn("size-3.5", cfg.spin && "animate-spin")} />
      {cfg.label}
    </span>
  )
}

export const EVIDENCE_KIND_ICON: Record<EvidenceKind, LucideIcon> = {
  commit: GitCommit,
  pull_request: GitPullRequest,
  deploy: Rocket,
  code_owner: Users,
  log: ScrollText,
  metric: Clock,
  error_group: ShieldAlert,
  service_map: Network,
}

export const EVIDENCE_KIND_LABEL: Record<EvidenceKind, string> = {
  commit: "Commit",
  pull_request: "Pull Request",
  deploy: "Deploy",
  code_owner: "Code Owner",
  log: "Log",
  metric: "Metric",
  error_group: "Error Group",
  service_map: "Service Map",
}

export const ACTION_KIND_CONFIG: Record<ActionKind, { label: string; icon: LucideIcon; className: string }> = {
  immediate_mitigation: {
    label: "Immediate mitigation",
    icon: AlertTriangle,
    className: "text-destructive",
  },
  verification: { label: "Verification", icon: Info, className: "text-primary" },
  durable_fix: { label: "Durable fix", icon: Wrench, className: "text-success" },
}
