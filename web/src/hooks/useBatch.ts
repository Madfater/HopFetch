import { useQueries } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Resolved } from '../api/types'
import { RESOLVE_KEY } from '../lib/tasks'
import type { BatchLink } from '../lib/url'

// - Asks /api/resolve about every link of a pasted batch, at most BATCH_CONCURRENCY at a time,
//   so a long list does not flood the hosts.
// - Each lookup uses the same query key as a single link, so a link checked on its own and in a
//   batch shares one cached answer.

export const BATCH_CONCURRENCY = 3

// - Runs at most `size` tasks at once; the others wait and start in the order they arrived.
export function limiter(size: number) {
  let running = 0
  const waiting: (() => void)[] = []
  const next = () => {
    if (running >= size) return
    const start = waiting.shift()
    if (!start) return
    running += 1
    start()
  }
  return <T>(task: () => Promise<T>): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      waiting.push(() => {
        task().then(resolve, reject).finally(() => {
          running -= 1
          next()
        })
      })
      next()
    })
}

const resolveSlot = limiter(BATCH_CONCURRENCY)

export interface BatchItem {
  link: BatchLink
  pending: boolean
  data: Resolved | undefined
  error: unknown
}

export function useBatch(links: BatchLink[]): BatchItem[] {
  const results = useQueries({
    queries: links.map((link) => ({
      queryKey: [...RESOLVE_KEY, link.url],
      queryFn: ({ signal }: { signal: AbortSignal }) => resolveSlot(() => api.resolve(link.url, signal)),
      retry: false,
      staleTime: 15_000,
      gcTime: 60_000,
    })),
  })
  return links.map((link, i) => ({
    link,
    pending: results[i].isPending,
    data: results[i].data,
    error: results[i].error,
  }))
}
