import Link from "next/link"
import { Card, CardContent } from "@/components/ui/card"
import { AnimatedSection } from "@/components/landing/animated-section"

const SECTIONS = [
  {
    id: "spherex",
    title: "What is SPHEREx?",
    body: [
      "SPHEREx is a NASA space telescope launched in March 2025. It takes pictures of the whole sky in infrared light (heat-like light our eyes cannot see), from 0.75 to 5 micrometres.",
      "It circles the Earth and scans the sky in strips, covering everything once every six months. So by late 2026 most places on the sky have been photographed three times, and the regions around the ecliptic poles hundreds of times.",
      "Its pixels are big: 6.15 arcseconds each. (An arcsecond is 1/3600 of a degree; the full Moon is about 1,800 arcseconds wide.)",
    ],
  },
  {
    id: "bands",
    title: "102 colours of infrared",
    body: [
      "SPHEREx has six detectors (D1 to D6). In front of each is a special filter whose colour changes smoothly from one edge of the detector to the other (a “linear variable filter”).",
      "As the telescope steps across the sky, a given star lands on a different part of the filter in each snapshot, so it is measured at a slightly different wavelength each time. Put together, these measurements give a spectrum with 102 colour channels.",
      "In Nexus Viewer you can stack whole detectors (D1–D6), pick one narrow channel, or mix three detectors into a false-colour picture.",
    ],
  },
  {
    id: "motion",
    title: "Why do stars move?",
    body: [
      "Stars orbit the centre of our galaxy, just like the Sun. Nearby ones seem to drift across the sky: this is called proper motion. Barnard’s Star, 6 light-years away, moves 10.4 arcseconds per year, the fastest of any star.",
      "Parallax is a different effect: as the Earth goes round the Sun, nearby stars seem to wobble back and forth by a tiny amount (less than one arcsecond, well below a SPHEREx pixel).",
      "Objects in our Solar System (asteroids, comets) move much faster: they can cross a whole SPHEREx picture in hours, so they appear in single exposures only.",
    ],
  },
  {
    id: "brown-dwarfs",
    title: "Brown dwarfs: failed stars",
    body: [
      "Brown dwarfs are balls of gas too small to burn hydrogen like the Sun. They are cool and very faint, and give off most of their light in the infrared.",
      "WISE 0855−0714 is the coldest known (about −25 °C, colder than a freezer). It is basically invisible below 3 micrometres and only shows up in SPHEREx’s longest-wavelength detectors (D5 and D6). That is why choosing the right band matters!",
      "Because they are faint, brown dwarfs are often found close to the Sun only when someone notices them moving. The citizen-science project Backyard Worlds found dozens this way by blinking WISE images.",
    ],
  },
  {
    id: "variables",
    title: "Variable stars",
    body: [
      "Some stars change brightness. R Draconis is a Mira variable: a giant red star that swells and shrinks with a period of about 245 days, changing brightness by a large factor.",
      "RW Aurigae is a very young star still surrounded by the disk of gas and dust it formed from; clumps in that disk pass in front of it and dim it irregularly.",
      "Click a star in the viewer to see its light curve (brightness against time) and how its spectrum changes.",
    ],
  },
  {
    id: "flags",
    title: "Reading the flags",
    body: [
      "The SPHEREx pipeline marks pixels it does not trust: saturated by a bright star, hit by a cosmic ray, affected by a “ghost” reflection of a bright star, persistent charge from an earlier exposure, and so on.",
      "Nexus Viewer leaves flagged pixels out when combining exposures, and the “Bad-pixel flags” overlay colours them so you can tell a real discovery from an artefact.",
      "Golden rule: if something appears in only one exposure and sits on a flagged pixel, it is almost certainly not real.",
    ],
  },
  {
    id: "difference",
    title: "Using difference images",
    body: [
      "Subtract an earlier picture from a later one and everything that stayed the same cancels to grey. A star that moved becomes a black-and-white pair (where it was, where it is now). A star that brightened becomes white.",
      "This is how Clyde Tombaugh found Pluto in 1930 (by blinking photographic plates) and how many brown dwarfs and asteroids are found today.",
    ],
  },
]

export default function LearnPage() {
  return (
    <main id="main" className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="mb-2 text-3xl font-bold">Learn the science</h1>
      <p className="mb-8 text-muted-foreground">Everything you need to understand what the viewer shows, no astronomy degree required.</p>
      <nav className="mb-8 flex flex-wrap gap-2 text-sm" aria-label="Sections">
        {SECTIONS.map((s) => <a key={s.id} href={`#${s.id}`} className="rounded-full border border-border px-3 py-1 hover:border-primary">{s.title}</a>)}
      </nav>
      <div className="space-y-6">
        {SECTIONS.map((s) => (
          <AnimatedSection key={s.id}>
            <Card id={s.id} className="scroll-mt-20 bg-card/70">
              <CardContent className="space-y-3 p-6">
                <h2 className="text-xl font-semibold">{s.title}</h2>
                {s.body.map((p, i) => <p key={i} className="text-sm leading-relaxed text-muted-foreground">{p}</p>)}
              </CardContent>
            </Card>
          </AnimatedSection>
        ))}
      </div>
      <p className="mt-8 text-sm">Ready? <Link href="/explore" className="text-primary underline">Go blink some stars →</Link></p>
    </main>
  )
}
