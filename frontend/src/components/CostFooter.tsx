import { Clock, DollarSign, Wrench } from "lucide-react"
import { formatCost, formatDuration } from "@/lib/format"
import type { Investigation } from "@/lib/types"

/** Engineers trust tools that are honest about what they cost — this is deliberately
 * always visible once an investigation finishes, not tucked into a details panel. */
export function CostFooter({ investigation }: { investigation: Investigation }) {
  if (!investigation.wall_time_ms) return null

  return (
    <div className="flex items-center gap-4 border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
      <span className="flex items-center gap-1">
        <Clock className="size-3" />
        {formatDuration(investigation.wall_time_ms)}
      </span>
      <span className="flex items-center gap-1">
        <Wrench className="size-3" />
        {investigation.total_tool_calls} tool call{investigation.total_tool_calls === 1 ? "" : "s"}
      </span>
      <span className="flex items-center gap-1">
        <DollarSign className="size-3" />
        {formatCost(investigation.total_cost_usd)}
      </span>
    </div>
  )
}
