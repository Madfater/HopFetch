import { useEffect, useRef, useState } from 'react'
import type { Task } from '../api/types'
import { lastCompleted } from '../lib/tasks'

// - The `completed_at` mark of this browser's last visit to the download page, read when the
//   page opens or becomes visible again; null on a first visit or where storage is blocked.
// - Leaving the page, or hiding it, stores the newest `completed_at` of the list, so the next
//   visit counts only tasks that finished after it. The mark comes from the server clock, so
//   a browser clock that runs off does not matter.
// - Nothing is stored before the list has loaded.

export const LAST_VISIT_STORAGE_KEY = 'last-visit-completed'

function read(): number | null {
  try {
    const value = Number(localStorage.getItem(LAST_VISIT_STORAGE_KEY) ?? NaN)
    return Number.isFinite(value) ? value : null
  } catch {
    return null
  }
}

function store(list: Task[] | undefined) {
  if (!list) return
  const mark = Math.max(read() ?? 0, lastCompleted(list) ?? 0)
  try {
    localStorage.setItem(LAST_VISIT_STORAGE_KEY, String(mark))
  } catch {
    // - Storage may be blocked; every visit then counts as a first visit.
  }
}

export function useLastVisit(list: Task[] | undefined): number | null {
  const [seen, setSeen] = useState(read)
  const listRef = useRef(list)
  useEffect(() => {
    listRef.current = list
  }, [list])

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') store(listRef.current)
      else setSeen(read())
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      store(listRef.current)
    }
  }, [])

  return seen
}
