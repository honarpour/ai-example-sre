import { Activity, PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import type { ImperativePanelHandle } from "react-resizable-panels"
import { AlertsInbox } from "@/components/AlertsInbox"
import { CreateAlertDialog } from "@/components/CreateAlertDialog"
import { InvestigationView } from "@/components/InvestigationView"
import { Button } from "@/components/ui/button"
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable"
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip"
import { useInvestigations } from "@/hooks/useInvestigations"

function useHashRoute(): [string | undefined, (id: string | undefined) => void] {
  const parse = () => {
    const match = /^#\/investigations\/(.+)$/.exec(window.location.hash)
    return match ? match[1] : undefined
  }
  const [id, setId] = useState<string | undefined>(parse)

  useEffect(() => {
    const onHashChange = () => setId(parse())
    window.addEventListener("hashchange", onHashChange)
    return () => window.removeEventListener("hashchange", onHashChange)
  }, [])

  const navigate = (newId: string | undefined) => {
    window.location.hash = newId ? `/investigations/${newId}` : "/"
  }

  return [id, navigate]
}

function App() {
  const { investigations, loading, addOptimistic } = useInvestigations()
  const [selectedId, navigate] = useHashRoute()
  const sidebarRef = useRef<ImperativePanelHandle>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      // Never hijack a keystroke the user is typing into a field, and never fight
      // a dialog's own Escape handling (Radix closes the dialog itself; without
      // this check our own Escape branch would ALSO navigate away underneath it).
      const tag = document.activeElement?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return
      if (document.querySelector('[role="dialog"]')) return

      if (e.key === "Escape" && selectedId) {
        navigate(undefined)
        return
      }
      if ((e.key === "j" || e.key === "k") && investigations.length > 0) {
        // idx is -1 when nothing is selected, so "j" from the inbox correctly
        // lands on row 0 rather than requiring a selection to already exist.
        const idx = investigations.findIndex((i) => i.id === selectedId)
        const nextIdx =
          e.key === "j" ? Math.min(idx + 1, investigations.length - 1) : Math.max(idx - 1, 0)
        navigate(investigations[nextIdx]?.id)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [selectedId, investigations, navigate])

  return (
    <TooltipProvider delayDuration={150}>
      {/* Sizes persist per-browser via autoSaveId (localStorage), same as the
          investigation view's own panels. */}
      <ResizablePanelGroup
        direction="horizontal"
        autoSaveId="app-shell-panels"
        // ResizablePanelGroup sets its own inline height: 100% (see index.css for why
        // html/body/#root need an explicit height for that to resolve to anything real);
        // h-dvh here would just be silently overridden by that inline style.
        className="h-full bg-background text-foreground"
      >
        <ResizablePanel
          ref={sidebarRef}
          id="sidebar"
          order={1}
          defaultSize={22}
          minSize={15}
          maxSize={40}
          collapsible
          collapsedSize={0}
          onCollapse={() => setSidebarCollapsed(true)}
          onExpand={() => setSidebarCollapsed(false)}
        >
          <aside className="flex h-full min-h-0 flex-col border-r border-border">
            <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
              <div className="flex items-center gap-2">
                <Activity className="size-4 text-primary" />
                <h1 className="text-sm font-semibold">AI SRE Investigator</h1>
              </div>
              <div className="flex items-center gap-1">
                <CreateAlertDialog
                  onCreated={(inv) => {
                    addOptimistic(inv)
                    navigate(inv.id)
                  }}
                />
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7 shrink-0"
                      onClick={() => sidebarRef.current?.collapse()}
                    >
                      <PanelLeftClose className="size-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Collapse sidebar</TooltipContent>
                </Tooltip>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <AlertsInbox
                investigations={investigations}
                loading={loading}
                selectedId={selectedId}
                onSelect={navigate}
              />
            </div>
          </aside>
        </ResizablePanel>

        <ResizableHandle />

        <ResizablePanel id="main" order={2} minSize={40}>
          <main className="relative h-full min-h-0 min-w-0">
            {sidebarCollapsed && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="absolute left-2 top-2 z-10 size-7 bg-background/80 backdrop-blur"
                    onClick={() => sidebarRef.current?.expand()}
                  >
                    <PanelLeftOpen className="size-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">Expand sidebar</TooltipContent>
              </Tooltip>
            )}
            {selectedId ? (
              <InvestigationView
                investigationId={selectedId}
                onBack={() => navigate(undefined)}
                onRerun={(inv) => {
                  addOptimistic(inv)
                  navigate(inv.id)
                }}
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted-foreground">
                <Activity className="size-10 opacity-30" />
                <p className="text-sm">Select an alert, or create one to start an investigation.</p>
              </div>
            )}
          </main>
        </ResizablePanel>
      </ResizablePanelGroup>
    </TooltipProvider>
  )
}

export default App
