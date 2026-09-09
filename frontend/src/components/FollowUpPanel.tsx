import { Loader2, MessageCircleQuestion, Send } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api, ApiError } from "@/lib/api"
import type { Evidence } from "@/lib/types"

interface QaTurn {
  question: string
  answer: string
  citedEvidenceIds: string[]
}

/** Turns the investigation from a static report into something you can actually
 * interrogate — resumes the same agent session server-side so the answer is
 * grounded in evidence it already gathered, not a fresh cold read. */
export function FollowUpPanel({
  investigationId,
  evidence,
  disabled,
  onCiteEvidence,
}: {
  investigationId: string
  evidence: Evidence[]
  disabled: boolean
  onCiteEvidence: (id: string) => void
}) {
  const [question, setQuestion] = useState("")
  const [turns, setTurns] = useState<QaTurn[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const evidenceById = new Map(evidence.map((e) => [e.id!, e]))

  const ask = async () => {
    const q = question.trim()
    if (!q || loading) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.askFollowUp(investigationId, q)
      setTurns((prev) => [...prev, { question: q, answer: res.answer, citedEvidenceIds: res.cited_evidence_ids }])
      setQuestion("")
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.status === 409
            ? "This investigation has no resumable session (likely from a previous session)."
            : e.message
          : "Failed to get an answer.",
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <MessageCircleQuestion className="size-3.5" />
        Ask a follow-up
      </div>

      {turns.map((turn, i) => (
        <div key={i} className="space-y-1 border-b border-border pb-2 last:border-0 last:pb-0">
          <p className="text-xs font-medium text-foreground/80">{turn.question}</p>
          <p className="text-sm text-muted-foreground">{turn.answer}</p>
          {turn.citedEvidenceIds.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-0.5">
              {turn.citedEvidenceIds.map((id) => {
                const e = evidenceById.get(id)
                if (!e) return null
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => onCiteEvidence(id)}
                    className="rounded-full border border-border bg-muted/50 px-2 py-0.5 text-[10px] hover:border-primary/50"
                  >
                    {e.title}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      ))}

      {disabled ? (
        <p className="text-xs text-muted-foreground">
          Available once the investigation finishes.
        </p>
      ) : (
        <div className="flex items-center gap-2">
          <Input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
            placeholder="e.g. was this in the canary too?"
            disabled={loading}
            className="text-sm"
          />
          <Button size="icon" className="shrink-0" onClick={ask} disabled={loading || !question.trim()}>
            {loading ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
          </Button>
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
