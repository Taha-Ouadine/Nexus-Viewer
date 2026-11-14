"use client"

import { Info } from "lucide-react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

/** A small (i) icon that explains a control in one sentence. */
export function InfoTip({ text }: { text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" className="inline-flex text-muted-foreground hover:text-foreground" aria-label={text}>
          <Info className="h-3.5 w-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-xs">{text}</TooltipContent>
    </Tooltip>
  )
}

export function ControlLabel({ children, tip }: { children: React.ReactNode; tip: string }) {
  return (
    <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
      {children}
      <InfoTip text={tip} />
    </div>
  )
}
