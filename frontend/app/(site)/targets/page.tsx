import { FeaturedTargets } from "@/components/site/featured-targets"

export default function TargetsPage() {
  return (
    <main id="main" className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="mb-2 text-3xl font-bold">Featured targets</h1>
      <p className="mb-8 max-w-3xl text-muted-foreground">
        The five test objects of the challenge plus a few bonus fields. Previews are real SPHEREx frames made by
        Nexus Viewer. The view opens centred where the object is <i>now</i> (2026): fast stars have moved up to 4.5
        arcminutes since their year-2000 catalogue positions.
      </p>
      <FeaturedTargets all />
    </main>
  )
}
