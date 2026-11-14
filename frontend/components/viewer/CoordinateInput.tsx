"use client"

import { useState } from "react"
import { Loader2, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { parseCoordPair } from "@/lib/coords"

export interface ResolvedInput {
  kind: "coords" | "name"
  ra?: number
  dec?: number
  name?: string
}

/** One box for "133.795 -7.245", "08h55m10.8s -07d14m42s" or a name ("Barnard's Star"). */
export function CoordinateInput({
  onSubmit, busy, placeholder, size = "default",
}: {
  onSubmit: (v: ResolvedInput) => void
  busy?: boolean
  placeholder?: string
  size?: "default" | "lg"
}) {
  const [text, setText] = useState("")
  const submit = () => {
    const t = text.trim()
    if (!t) return
    const c = parseCoordPair(t)
    onSubmit(c ? { kind: "coords", ra: c.ra, dec: c.dec } : { kind: "name", name: t })
  }
  return (
    <form
      className="flex w-full gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <Input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder ?? "Star name or RA Dec (e.g. Barnard's Star, or 269.446 4.768)"}
        aria-label="Object name or coordinates"
        className={size === "lg" ? "h-12 text-base" : ""}
      />
      <Button type="submit" disabled={busy} className={size === "lg" ? "h-12 px-6" : ""}>
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
        <span className="ml-1">Go</span>
      </Button>
    </form>
  )
}
