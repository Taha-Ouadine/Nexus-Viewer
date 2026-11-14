import type { Metadata } from "next"
import { GeistSans } from "geist/font/sans"
import { GeistMono } from "geist/font/mono"
import { Providers } from "@/components/site/providers"
import "./globals.css"

export const metadata: Metadata = {
  title: "Nexus Viewer — catch the sky moving with SPHEREx",
  description:
    "Type a star name or position and watch every SPHEREx infrared image of that patch of sky play like a flip-book. NASA Space Apps Challenge 2026.",
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className={`font-sans ${GeistSans.variable} ${GeistMono.variable} min-h-screen`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
