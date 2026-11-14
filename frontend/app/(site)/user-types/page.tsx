import Link from "next/link"
import { Compass, Microscope } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default function UserTypes() {
  return (
    <main id="main" className="mx-auto max-w-5xl px-4 py-12">
      <h1 className="mb-2 text-center text-3xl font-bold">How do you want to explore?</h1>
      <p className="mb-10 text-center text-muted-foreground">Both modes use the same data. You can switch any time.</p>
      <div className="grid gap-6 md:grid-cols-2">
        <Card className="bg-card/70">
          <CardHeader><Compass className="h-8 w-8 text-primary" /><CardTitle>Explorer</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>For students, families and the curious. A big search box, one-click featured targets, a play button and plain-English hints.</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>“Make it pop” contrast slider</li>
              <li>“Show difference” switch to see only what changed</li>
              <li>Short / long / false-colour light</li>
              <li>“What am I looking at?” guide</li>
            </ul>
            <Button asChild className="w-full"><Link href="/explore">Start as Explorer</Link></Button>
          </CardContent>
        </Card>
        <Card className="bg-card/70">
          <CardHeader><Microscope className="h-8 w-8 text-primary" /><CardTitle>Researcher</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>Every control: detector bands, 102 narrow channels, false-colour presets, difference modes, epoch windows, stretch functions, Gaia/CatWISE overlays, flag masks, spectra, light curves and exports.</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>Every setting lives in the URL: share or embed any view</li>
              <li>GIF / PNG / FITS-cube downloads</li>
              <li>Aladin Lite sky context</li>
            </ul>
            <Button asChild variant="outline" className="w-full"><Link href="/viewer">Open the Researcher viewer</Link></Button>
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
