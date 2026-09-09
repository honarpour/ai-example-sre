import { Check, ThumbsDown, ThumbsUp } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

type State = "idle" | "submitting" | "submitted"

/** Feedback is the substrate for "how does this improve over time" (see debrief
 * notes) — every 👎 plus its optional actual-root-cause note is exactly the raw
 * material a future regression/eval suite would be built from (see PLAN.md
 * Phase 5). Recorded per-hypothesis, not per-investigation, since a multi-
 * hypothesis investigation can be right about one and wrong about another. */
export function FeedbackButtons({
  investigationId,
  hypothesisId,
}: {
  investigationId: string
  hypothesisId: string
}) {
  const [helpful, setHelpful] = useState<boolean | null>(null)
  const [state, setState] = useState<State>("idle")
  const [note, setNote] = useState("")
  const [noteSubmitted, setNoteSubmitted] = useState(false)
  const [noteSubmitting, setNoteSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const vote = async (value: boolean) => {
    setHelpful(value)
    setState("submitting")
    setError(null)
    try {
      await api.submitFeedback(investigationId, { hypothesis_id: hypothesisId, helpful: value })
      setState("submitted")
    } catch {
      setState("idle")
      setHelpful(null)
      setError("Couldn't record that — try again.")
    }
  }

  const submitNote = async () => {
    if (!note.trim() || helpful === null || noteSubmitting) return
    setNoteSubmitting(true)
    setError(null)
    try {
      await api.submitFeedback(investigationId, {
        hypothesis_id: hypothesisId,
        helpful,
        actual_root_cause: note.trim(),
      })
      setNoteSubmitted(true)
    } catch {
      setError("Couldn't save that note — try again.")
    } finally {
      setNoteSubmitting(false)
    }
  }

  if (state === "idle" || state === "submitting") {
    return (
      <div className="space-y-1">
        <div className="flex items-center gap-1">
          <span className="text-[11px] text-muted-foreground">Helpful?</span>
          <Button
            variant="ghost"
            size="icon"
            className="size-6"
            disabled={state === "submitting"}
            onClick={() => vote(true)}
            aria-label="Mark as helpful"
          >
            <ThumbsUp className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-6"
            disabled={state === "submitting"}
            onClick={() => vote(false)}
            aria-label="Mark as not helpful"
          >
            <ThumbsDown className="size-3.5" />
          </Button>
        </div>
        {error && <p className="text-[11px] text-destructive">{error}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      <div className={cn("flex items-center gap-1.5 text-[11px]", "text-success")}>
        <Check className="size-3" />
        Thanks — feedback recorded.
      </div>
      {helpful === false && !noteSubmitted && (
        <div className="flex items-start gap-1.5">
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What was the actual root cause? (optional)"
            rows={2}
            className="text-xs"
            disabled={noteSubmitting}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={submitNote}
            disabled={!note.trim() || noteSubmitting}
          >
            Add
          </Button>
        </div>
      )}
      {noteSubmitted && <p className="text-[11px] text-muted-foreground">Note added — thank you.</p>}
      {error && <p className="text-[11px] text-destructive">{error}</p>}
    </div>
  )
}
