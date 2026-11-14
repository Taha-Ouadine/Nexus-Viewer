"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useState } from "react"
import { Menu, Orbit, X } from "lucide-react"
import { Button } from "@/components/ui/button"

const LINKS = [
  { href: "/explore", label: "Explore" },
  { href: "/viewer", label: "Viewer" },
  { href: "/targets", label: "Targets" },
  { href: "/learn", label: "Learn" },
  { href: "/about", label: "About" },
]

export function SiteNav() {
  const path = usePathname()
  const [open, setOpen] = useState(false)
  return (
    <header className="sticky top-0 z-40 border-b border-border/50 bg-background/80 backdrop-blur-md">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-1">
        Skip to content
      </a>
      <nav className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4" aria-label="Main">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <Orbit className="h-5 w-5 text-primary" />
          Nexus <span className="text-primary">Viewer</span>
        </Link>
        <div className="hidden gap-1 md:flex">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href}
              className={`rounded-md px-3 py-1.5 text-sm transition hover:bg-primary/15 ${path?.startsWith(l.href) ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}>
              {l.label}
            </Link>
          ))}
        </div>
        <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setOpen(!open)} aria-label="Toggle menu" aria-expanded={open}>
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </Button>
      </nav>
      {open && (
        <div className="border-t border-border/50 px-4 py-2 md:hidden">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setOpen(false)} className="block rounded px-2 py-2 text-sm hover:bg-primary/15">{l.label}</Link>
          ))}
        </div>
      )}
    </header>
  )
}
