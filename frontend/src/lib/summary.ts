import type { Investigation } from "@/lib/types"

/** A copy-pasteable incident summary in Slack's mrkdwn dialect (*bold*, not
 * markdown's **bold**) — meant to go straight into an incident channel. */
export function buildSlackSummary(investigation: Investigation): string {
  const { alert } = investigation
  const lines: string[] = [
    `*${alert.title}* (${alert.severity.toUpperCase()}) — _${alert.service}_`,
    "",
  ]

  if (investigation.tldr) {
    lines.push(investigation.tldr, "")
  }

  const top = investigation.hypotheses.find((h) => h.rank === 1)
  if (top) {
    lines.push(`*Root cause (${top.confidence} confidence):* ${top.summary}`, "")
    if (top.suggested_actions.length > 0) {
      lines.push("*Suggested actions:*")
      for (const action of top.suggested_actions) {
        lines.push(`• ${action.title}${action.command ? ` — \`${action.command}\`` : ""}`)
      }
      lines.push("")
    }
  }

  lines.push(`<${window.location.origin}${window.location.pathname}#/investigations/${investigation.id}|View full investigation>`)

  return lines.join("\n")
}
