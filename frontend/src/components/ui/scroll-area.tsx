import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area"
import type * as React from "react"
import { cn } from "@/lib/utils"

function ScrollArea({
  className,
  children,
  horizontal = false,
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.Root> & {
  /** Also render a horizontal scrollbar, for content (e.g. long tool-call lines)
   * that shouldn't wrap or truncate but should still be fully reachable. */
  horizontal?: boolean
}) {
  return (
    <ScrollAreaPrimitive.Root className={cn("relative overflow-hidden", className)} {...props}>
      <ScrollAreaPrimitive.Viewport className="size-full rounded-[inherit]">
        {children}
      </ScrollAreaPrimitive.Viewport>
      <ScrollAreaPrimitive.Scrollbar
        orientation="vertical"
        className="flex touch-none select-none border-l border-l-transparent p-px transition-colors w-2.5"
      >
        <ScrollAreaPrimitive.Thumb className="relative flex-1 rounded-full bg-border" />
      </ScrollAreaPrimitive.Scrollbar>
      {horizontal && (
        <ScrollAreaPrimitive.Scrollbar
          orientation="horizontal"
          className="flex touch-none select-none border-t border-t-transparent p-px transition-colors h-2.5"
        >
          <ScrollAreaPrimitive.Thumb className="relative flex-1 rounded-full bg-border" />
        </ScrollAreaPrimitive.Scrollbar>
      )}
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  )
}

export { ScrollArea }
