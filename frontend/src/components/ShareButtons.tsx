import { Check, Link2, MessagesSquare } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { buildSlackSummary } from "@/lib/summary"
import type { Investigation } from "@/lib/types"

function useCopiedFlash() {
  const [copied, setCopied] = useState(false)
  const flash = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard API can be unavailable - fail silently, nothing destructive happened
    }
  }
  return { copied, flash }
}

export function ShareButtons({ investigation }: { investigation: Investigation }) {
  const permalink = useCopiedFlash()
  const summary = useCopiedFlash()

  return (
    <div className="flex items-center gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={() => permalink.flash(`${window.location.origin}${window.location.pathname}#/investigations/${investigation.id}`)}
            aria-label="Copy permalink"
          >
            {permalink.copied ? <Check className="size-3.5 text-success" /> : <Link2 className="size-3.5" />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>Copy permalink</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={() => summary.flash(buildSlackSummary(investigation))}
            aria-label="Copy Slack summary"
          >
            {summary.copied ? <Check className="size-3.5 text-success" /> : <MessagesSquare className="size-3.5" />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>Copy Slack-ready summary</TooltipContent>
      </Tooltip>
    </div>
  )
}
