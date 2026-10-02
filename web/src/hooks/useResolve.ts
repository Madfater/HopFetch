import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Provider, Resolved } from '../api/types'
import { isHttpUrl, matchProvider, normalizeUrl } from '../lib/url'

// - Checks the input locally against the provider patterns, then asks /api/resolve.
// - Typed input waits RESOLVE_DELAY_MS after the last change; pasted or dropped input is
//   checked at once.
// - Each lookup is keyed by the normalized URL, so an older answer can never stand in for a
//   newer input, and a request whose key is no longer in use is aborted through its signal.

export const RESOLVE_DELAY_MS = 400

export type Local =
  | { kind: 'empty' }
  | { kind: 'invalid' }
  | { kind: 'unsupported' }
  | { kind: 'matched'; url: string; provider: Provider }

export function checkLocally(input: string, providers: Provider[]): Local {
  const text = input.trim()
  if (!text) return { kind: 'empty' }
  if (!isHttpUrl(text)) return { kind: 'invalid' }
  const match = matchProvider(text, providers)
  if (!match) return { kind: 'unsupported' }
  return { kind: 'matched', url: normalizeUrl(text), provider: match.provider }
}

export interface ResolveState {
  local: Local
  pending: boolean
  data: Resolved | undefined
  error: unknown
}

// - `immediate` is a counter the caller bumps on paste or drop, which skips the delay for the
//   current input.
export function useResolve(input: string, providers: Provider[], immediate: number): ResolveState {
  const local = checkLocally(input, providers)
  const candidate = local.kind === 'matched' ? local.url : null
  const [target, setTarget] = useState<string | null>(null)
  const [lastImmediate, setLastImmediate] = useState(immediate)

  if (immediate !== lastImmediate) {
    setLastImmediate(immediate)
    setTarget(candidate)
  }

  useEffect(() => {
    if (candidate === null) return
    const timer = setTimeout(() => setTarget(candidate), RESOLVE_DELAY_MS)
    return () => clearTimeout(timer)
  }, [candidate])

  const active = candidate === null ? null : target
  const query = useQuery({
    queryKey: ['resolve', active],
    queryFn: ({ signal }) => api.resolve(active as string, signal),
    enabled: active !== null,
    retry: false,
    staleTime: 15_000,
    gcTime: 60_000,
  })

  const current = active !== null && active === candidate
  return {
    local,
    pending: candidate !== null && (!current || query.isFetching),
    data: current ? query.data : undefined,
    error: current ? query.error : null,
  }
}
