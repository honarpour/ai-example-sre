import { AlertTriangle, Loader2, Sparkles } from "lucide-react"
import { useEffect, useState } from "react"
import { SeverityBadge } from "@/components/badges"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { api, ApiError } from "@/lib/api"
import type { Investigation, ScenarioSummary, Severity } from "@/lib/types"

const BACKEND_ORIGIN = typeof window !== "undefined" ? window.location.origin : ""

export function CreateAlertDialog({
  onCreated,
}: {
  onCreated: (investigation: Investigation) => void
}) {
  const [open, setOpen] = useState(false)
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([])
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [customTitle, setCustomTitle] = useState("")
  const [customService, setCustomService] = useState("")
  const [customSeverity, setCustomSeverity] = useState<Severity>("high")
  const [customMessage, setCustomMessage] = useState("")
  const [customStackTrace, setCustomStackTrace] = useState("")

  useEffect(() => {
    if (open && scenarios.length === 0) {
      api.listScenarios().then(setScenarios).catch(() => setError("Couldn't load scenario presets."))
    }
  }, [open, scenarios.length])

  const createFromScenario = async (key: string) => {
    setBusyKey(key)
    setError(null)
    try {
      const investigation = await api.createAlert({ scenario: key, source: "manual" })
      onCreated(investigation)
      setOpen(false)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to create alert.")
    } finally {
      setBusyKey(null)
    }
  }

  const createCustom = async () => {
    if (!customTitle || !customService || !customMessage) {
      setError("Title, service, and message are required.")
      return
    }
    setBusyKey("custom")
    setError(null)
    try {
      const investigation = await api.createAlert({
        title: customTitle,
        service: customService,
        severity: customSeverity,
        message: customMessage,
        stack_trace: customStackTrace || null,
        source: "manual",
      })
      onCreated(investigation)
      setOpen(false)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to create alert.")
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" className="gap-1.5">
          <AlertTriangle className="size-4" />
          Create Alert
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Fire an alert</DialogTitle>
          <DialogDescription>
            Pick a scenario to see the investigator in action, or send a custom alert.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="presets">
          <TabsList className="w-full">
            <TabsTrigger value="presets" className="flex-1">
              Scenario presets
            </TabsTrigger>
            <TabsTrigger value="custom" className="flex-1">
              Custom alert
            </TabsTrigger>
            <TabsTrigger value="webhook" className="flex-1">
              Webhook
            </TabsTrigger>
          </TabsList>

          <TabsContent value="presets" className="space-y-2">
            {scenarios.length === 0 && (
              <div className="flex items-center justify-center py-8 text-muted-foreground text-sm">
                <Loader2 className="size-4 animate-spin mr-2" /> Loading scenarios...
              </div>
            )}
            {scenarios.map((s) => (
              <button
                key={s.key}
                type="button"
                disabled={busyKey !== null}
                onClick={() => createFromScenario(s.key)}
                className="w-full text-left rounded-lg border border-border bg-card p-3 transition-colors hover:border-primary/50 hover:bg-accent/50 disabled:opacity-60"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-sm">{s.name}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    <SeverityBadge severity={s.severity} />
                    {busyKey === s.key && <Loader2 className="size-3.5 animate-spin text-primary" />}
                  </div>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{s.description}</p>
                <p className="mt-1.5 font-mono text-[11px] text-muted-foreground/70">{s.service}</p>
              </button>
            ))}
          </TabsContent>

          <TabsContent value="custom" className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="ca-title">Title</Label>
                <Input id="ca-title" value={customTitle} onChange={(e) => setCustomTitle(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ca-service">Service</Label>
                <Input
                  id="ca-service"
                  value={customService}
                  onChange={(e) => setCustomService(e.target.value)}
                  placeholder="payments-api"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Severity</Label>
              <Select value={customSeverity} onValueChange={(v) => setCustomSeverity(v as Severity)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="critical">Critical</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="low">Low</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ca-message">Message</Label>
              <Textarea
                id="ca-message"
                rows={2}
                value={customMessage}
                onChange={(e) => setCustomMessage(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ca-stack">Stack trace (optional)</Label>
              <Textarea
                id="ca-stack"
                rows={3}
                className="font-mono text-xs"
                value={customStackTrace}
                onChange={(e) => setCustomStackTrace(e.target.value)}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Note: without a matching scenario, the mock data layer has nothing to investigate —
              this alert will complete with no evidence. Custom alerts are for exercising the UI;
              use a preset to see a real investigation.
            </p>
            <Button onClick={createCustom} disabled={busyKey !== null} className="w-full gap-1.5">
              {busyKey === "custom" ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
              Fire alert
            </Button>
          </TabsContent>

          <TabsContent value="webhook" className="space-y-2">
            <p className="text-sm text-muted-foreground">
              A real alerting tool would POST here directly — same endpoint the button above uses:
            </p>
            <pre className="rounded-lg border border-border bg-muted/50 p-3 text-xs overflow-x-auto">
              {`curl -X POST ${BACKEND_ORIGIN}/api/alerts \\
  -H "Content-Type: application/json" \\
  -d '{
    "title": "High error rate: payments-api",
    "service": "payments-api",
    "severity": "critical",
    "message": "5xx rate exceeded 8% threshold",
    "source": "webhook"
  }'`}
            </pre>
          </TabsContent>
        </Tabs>

        {error && <p className="text-sm text-destructive">{error}</p>}
      </DialogContent>
    </Dialog>
  )
}
