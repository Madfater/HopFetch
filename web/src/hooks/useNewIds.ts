import { useEffect, useState } from 'react'

// - Tells which ids arrived after a list was first seen. The ids of the first render with a
//   loaded list are known; an id that shows up later is new for SETTLE_MS and known after
//   that. SETTLE_MS outlasts the 1.6s arrival flash, so a row that remounts later, such as
//   after a filter hid it, does not flash again.
// - A remount of the page starts over, so a page that opens shows no arrivals.

export const SETTLE_MS = 2000

export function useNewIds(ids: string[] | undefined): (id: string) => boolean {
  const [known, setKnown] = useState<ReadonlySet<string> | null>(() => (ids ? new Set(ids) : null))
  if (known === null && ids) setKnown(new Set(ids))

  const fresh = known && ids ? ids.filter((id) => !known.has(id)).join(' ') : ''
  useEffect(() => {
    if (!fresh) return
    const timer = window.setTimeout(() => setKnown((all) => new Set([...(all ?? []), ...fresh.split(' ')])), SETTLE_MS)
    return () => window.clearTimeout(timer)
  }, [fresh])

  return (id) => known !== null && !known.has(id)
}
