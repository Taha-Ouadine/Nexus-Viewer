"use client"

import { Code2, Download, Film, Image as ImageIcon, Link2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { api } from "@/lib/api"
import { serializeViewerState, type ViewerState } from "@/lib/url-state"

function siteUrl() {
  return process.env.NEXT_PUBLIC_SITE_URL || (typeof window !== "undefined" ? window.location.origin : "")
}

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(`${what} copied to clipboard`)
  } catch {
    toast.error("Could not access the clipboard", { description: text })
  }
}

export function ExportMenu({ state, hash, frameId, canvasPng }: {
  state: ViewerState
  hash: string | null
  frameId: string | null
  canvasPng?: () => string | null
}) {
  const qs = serializeViewerState(state).toString()
  const link = `${siteUrl()}/viewer?${qs}`
  const embed = `<iframe src="${siteUrl()}/embed?${qs}" width="420" height="520" style="border:0" title="Nexus Viewer: SPHEREx sky"></iframe>`
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="outline"><Download className="mr-1 h-4 w-4" />Share / export</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="text-xs">Share this exact view</DropdownMenuLabel>
        <DropdownMenuItem onClick={() => copy(link, "Link")}><Link2 className="mr-2 h-4 w-4" />Copy link</DropdownMenuItem>
        <DropdownMenuItem onClick={() => copy(embed, "Embed code")}><Code2 className="mr-2 h-4 w-4" />Copy embed code</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs">Download</DropdownMenuLabel>
        <DropdownMenuItem disabled={!hash} asChild>
          <a href={hash ? api.gifUrl(hash, { stretch: state.stretch === "zscale" ? "linear" : state.stretch, speed_ms: state.speed, size: 400, diff: state.diff }) : "#"} download="nexus-viewer.gif">
            <Film className="mr-2 h-4 w-4" />Animated GIF
          </a>
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={!frameId}
          onClick={() => {
            const data = canvasPng?.()
            const a = document.createElement("a")
            a.href = data ?? (frameId ? api.framePngUrl(frameId, state.stretch, 6) : "#")
            a.download = "nexus-viewer-frame.png"
            a.click()
          }}
        >
          <ImageIcon className="mr-2 h-4 w-4" />PNG of this frame
        </DropdownMenuItem>
        <DropdownMenuItem disabled={!hash} asChild>
          <a href={hash ? api.fitsUrl(hash) : "#"} download><Download className="mr-2 h-4 w-4" />FITS cube (aligned frames)</a>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
