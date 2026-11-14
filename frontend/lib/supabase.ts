// Optional Supabase browser client (anon key only). Everything works without it:
// when the env vars are missing this returns null and the app polls the backend.
import { createClient, type SupabaseClient } from "@supabase/supabase-js"

let client: SupabaseClient | null | undefined

export function getSupabase(): SupabaseClient | null {
  if (client !== undefined) return client
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  client = url && key ? createClient(url, key) : null
  return client
}

/** Subscribe to progress of one job row via Realtime. Returns an unsubscribe function,
 *  or null when Supabase is not configured (caller should poll instead). */
export function subscribeToJob(jobId: string, onChange: () => void): (() => void) | null {
  const sb = getSupabase()
  if (!sb) return null
  const channel = sb
    .channel(`job-${jobId}`)
    .on("postgres_changes", { event: "UPDATE", schema: "public", table: "jobs", filter: `id=eq.${jobId}` }, onChange)
    .subscribe()
  return () => {
    void sb.removeChannel(channel)
  }
}
