import Link from "next/link"

/** Data credits required by IRSA and the other archives we use. */
export function DataCredits({ compact = false }: { compact?: boolean }) {
  return (
    <p className={compact ? "text-[11px] leading-relaxed text-muted-foreground" : "text-sm leading-relaxed text-muted-foreground"}>
      This research uses data from the SPHEREx mission, obtained from the NASA/IPAC Infrared Science Archive (IRSA),
      operated by the California Institute of Technology under contract with NASA. SPHEREx DR1:{" "}
      <a className="underline" href="https://doi.org/10.26131/IRSA678">doi:10.26131/IRSA678</a>; QR3:{" "}
      <a className="underline" href="https://doi.org/10.26131/IRSA662">doi:10.26131/IRSA662</a>. Also uses ESA Gaia DR3
      (DPAC), NASA WISE / CatWISE2020 (via IRSA), and the CDS Sesame resolver and Aladin Lite (CDS, Strasbourg).
    </p>
  )
}

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-border/50">
      <div className="mx-auto max-w-7xl space-y-3 px-4 py-8">
        <DataCredits compact />
        <p className="text-xs text-muted-foreground">
          Nexus Viewer · Team Nexus · NASA Space Apps Challenge 2026 — <i>Planet X and SPHEREx</i>.{" "}
          <Link href="/about" className="underline">About & credits</Link>
        </p>
      </div>
    </footer>
  )
}
