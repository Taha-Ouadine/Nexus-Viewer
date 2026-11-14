import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { DataCredits } from "@/components/site/site-footer"

export default function AboutPage() {
  return (
    <main id="main" className="mx-auto max-w-4xl space-y-6 px-4 py-10">
      <h1 className="text-3xl font-bold">About Nexus Viewer</h1>
      <p className="text-muted-foreground">
        Nexus Viewer is our entry to the 2026 NASA Space Apps Challenge <i>Planet X and SPHEREx</i>: a web tool that
        turns SPHEREx&apos;s repeated infrared images of the sky into flip-books, difference images, spectra and light
        curves, so anyone can look for things that move or change.
      </p>

      <Card className="bg-card/70">
        <CardHeader><CardTitle>Team Nexus</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {/* TODO: team members */}
          <p>Team members: to be added.</p>
        </CardContent>
      </Card>

      <Card className="bg-card/70">
        <CardHeader><CardTitle>Data & credits</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <DataCredits />
          <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
            <li>SPHEREx Data Release 1 — DOI <a className="underline" href="https://doi.org/10.26131/IRSA678">10.26131/IRSA678</a></li>
            <li>SPHEREx Quick Release 3 — DOI <a className="underline" href="https://doi.org/10.26131/IRSA662">10.26131/IRSA662</a></li>
            <li>Gaia DR3: European Space Agency mission Gaia, processed by the Gaia DPAC</li>
            <li>CatWISE2020 and AllWISE catalogues, served by IRSA</li>
            <li>CDS Sesame name resolver and Aladin Lite (CDS, Strasbourg Astronomical Observatory)</li>
            <li>Software: Astropy, astroquery, reproject, photutils, FastAPI, Next.js, three.js, Recharts</li>
          </ul>
        </CardContent>
      </Card>

      <Card className="bg-card/70">
        <CardHeader><CardTitle>Inspiration</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p><a className="underline" href="http://byw.tools/wiseview">WiseView</a>: the WISE image blinker used by citizen scientists; our URL format and blink speed follow it.</p>
          <p><a className="underline" href="https://backyardworlds.org">Backyard Worlds: Planet 9</a>: volunteers who found brown dwarfs by blinking images.</p>
          <p><a className="underline" href="https://irsa.ipac.caltech.edu/Missions/spherex.html">IRSA SPHEREx archive</a> and its tutorials.</p>
        </CardContent>
      </Card>
    </main>
  )
}
