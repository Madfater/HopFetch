import { useState } from 'react'

// - Tells which ids arrived after a list was first seen. The ids of the first render with a
//   loaded list are the known ones; any other id is new.
// - A remount starts over, so a page that opens shows no arrivals.

export function useNewIds(ids: string[] | undefined): (id: string) => boolean {
  const [known, setKnown] = useState<ReadonlySet<string> | null>(() => (ids ? new Set(ids) : null))
  if (known === null && ids) setKnown(new Set(ids))
  return (id) => known !== null && !known.has(id)
}
