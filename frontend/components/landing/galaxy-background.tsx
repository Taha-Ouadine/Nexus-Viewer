"use client"

import dynamic from "next/dynamic"
import { useEffect, useState } from "react"
import { ParallaxStars } from "./parallax-stars"

// three.js scene from last year's project, loaded only in the browser
const GalaxyScene = dynamic(() => import("./galaxy-scene").then((m) => m.GalaxyScene), { ssr: false })

/** Galaxy + parallax stars. Skipped when the user prefers reduced motion. */
export function GalaxyBackground() {
  const [motion, setMotion] = useState(false)
  useEffect(() => {
    setMotion(!window.matchMedia("(prefers-reduced-motion: reduce)").matches)
  }, [])
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 isolate">
      {motion && <GalaxyScene />}
      {motion && <ParallaxStars />}
    </div>
  )
}
