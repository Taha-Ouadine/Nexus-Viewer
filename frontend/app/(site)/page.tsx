import Link from "next/link"
import { ArrowRight, Film, MousePointerClick, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { GalaxyBackground } from "@/components/landing/galaxy-background"
import { AnimatedSection } from "@/components/landing/animated-section"
import { FeaturedTargets } from "@/components/site/featured-targets"

export default function Home() {
  return (
    <main id="main" className="relative">
      <GalaxyBackground />
      <section className="relative z-10 mx-auto flex min-h-[78vh] max-w-6xl flex-col items-center justify-center gap-8 px-4 py-16 text-center lg:flex-row lg:text-left">
        <div className="flex-1 space-y-6">
          <p className="text-sm uppercase tracking-[0.3em] text-primary">NASA Space Apps 2026 · Planet X and SPHEREx</p>
          <h1 className="text-5xl font-bold leading-tight md:text-6xl">
            Catch the sky <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">moving.</span>
          </h1>
          <p className="max-w-xl text-lg text-muted-foreground">
            Type a star name or a sky position. Nexus Viewer collects every image NASA&apos;s SPHEREx telescope took
            of that patch of sky, lines them up and plays them like a flip-book, so anything that moves or changes
            brightness stands out.
          </p>
          <div className="flex flex-wrap justify-center gap-3 lg:justify-start">
            <Button asChild size="lg"><Link href="/explore">Start exploring <ArrowRight className="ml-1 h-4 w-4" /></Link></Button>
            <Button asChild size="lg" variant="outline"><Link href="/user-types">Explorer or Researcher?</Link></Button>
          </div>
        </div>
        <div className="flex-1">
          <Card className="mx-auto max-w-sm overflow-hidden border-primary/40 bg-black/70 shadow-2xl">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/targets/barnards-star.gif" alt="Animated SPHEREx frames of Barnard's Star moving north between 2025 and 2026" className="aspect-square w-full" style={{ imageRendering: "pixelated" }} />
            <CardContent className="p-3 text-left text-sm text-muted-foreground">
              Barnard&apos;s Star, 3 SPHEREx sky surveys (Aug 2025 → Aug 2026). It creeps upward about one pixel every six months.
            </CardContent>
          </Card>
        </div>
      </section>

      <section className="relative z-10 mx-auto max-w-6xl px-4 py-12">
        <AnimatedSection>
          <h2 className="mb-8 text-center text-3xl font-bold">How it works</h2>
          <div className="grid gap-4 md:grid-cols-3">
            {[
              { icon: Search, t: "1 · Pick a spot", d: "Enter a name like “WISE 0855” or coordinates. We find every SPHEREx exposure that covers it, in all six infrared detectors." },
              { icon: Film, t: "2 · Watch the flip-book", d: "The images are cut out, aligned north-up and combined per sky survey. Blink them, zoom in, subtract them to see what changed." },
              { icon: MousePointerClick, t: "3 · Click to measure", d: "Click any star to measure its brightness in every exposure: a 0.75–5 µm spectrum and a light curve, made on the fly." },
            ].map((s) => (
              <Card key={s.t} className="bg-card/70 backdrop-blur">
                <CardContent className="space-y-2 p-6">
                  <s.icon className="h-7 w-7 text-primary" />
                  <h3 className="text-lg font-semibold">{s.t}</h3>
                  <p className="text-sm text-muted-foreground">{s.d}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </AnimatedSection>
      </section>

      <section className="relative z-10 mx-auto max-w-6xl px-4 py-12">
        <AnimatedSection>
          <h2 className="mb-2 text-center text-3xl font-bold">Featured targets</h2>
          <p className="mb-8 text-center text-muted-foreground">The five objects from the challenge, ready to play.</p>
          <FeaturedTargets limit={5} />
          <div className="mt-6 text-center"><Button asChild variant="outline"><Link href="/targets">All targets</Link></Button></div>
        </AnimatedSection>
      </section>
    </main>
  )
}
