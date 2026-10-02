import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import providers from '../../../shared/providers.json'
import { api } from '../api/client'
import type { Resolved } from '../api/types'
import { RESOLVE_DELAY_MS, useResolve } from './useResolve'

const A = 'https://k2s.cc/file/aaa111/a.rar'
const B = 'https://k2s.cc/file/bbb222/b.rar'

function resolved(fileId: string): Resolved {
  return {
    provider: 'k2s', file_id: fileId, file_name: `${fileId}.rar`, size: 10, resumable: true,
    duplicate: null, free_bytes: 100, required_bytes: 20,
  }
}

// - A controllable fake of api.resolve: each call waits until the test settles it, and records
//   whether its signal was aborted.
function fakeResolve() {
  const calls: { url: string; signal?: AbortSignal; settle: () => void }[] = []
  const spy = vi.spyOn(api, 'resolve').mockImplementation((url, signal) =>
    new Promise<Resolved>((resolve, reject) => {
      const fileId = url.split('/')[4]
      calls.push({ url, signal, settle: () => resolve(resolved(fileId)) })
      signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }),
  )
  return { calls, spy }
}

// - Settles one fake request and lets the query cache deliver the result, which it schedules
//   on a timer.
async function settle(call: { settle: () => void }) {
  await act(async () => {
    call.settle()
    await vi.advanceTimersByTimeAsync(10)
  })
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return renderHook(({ input, immediate }) => useResolve(input, providers, immediate), {
    wrapper,
    initialProps: { input: '', immediate: 0 },
  })
}

describe('useResolve', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('waits for typing to stop before asking the backend', async () => {
    const { calls } = fakeResolve()
    const hook = setup()
    hook.rerender({ input: 'https://k2s.cc/file/aaa', immediate: 0 })
    await act(() => vi.advanceTimersByTimeAsync(RESOLVE_DELAY_MS / 2))
    hook.rerender({ input: A, immediate: 0 })
    await act(() => vi.advanceTimersByTimeAsync(RESOLVE_DELAY_MS - 1))
    expect(calls.map((c) => c.url)).toEqual([])
    expect(hook.result.current.pending).toBe(true)
    await act(() => vi.advanceTimersByTimeAsync(1))
    expect(calls.map((c) => c.url)).toEqual([A])
  })

  it('asks at once after a paste', async () => {
    const { calls } = fakeResolve()
    const hook = setup()
    hook.rerender({ input: A, immediate: 1 })
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(calls.map((c) => c.url)).toEqual([A])
    await settle(calls[0])
    expect(hook.result.current.data?.file_id).toBe('aaa111')
    expect(hook.result.current.pending).toBe(false)
  })

  it('aborts an outdated request and never shows its late answer', async () => {
    const { calls } = fakeResolve()
    const hook = setup()
    hook.rerender({ input: A, immediate: 1 })
    await act(() => vi.advanceTimersByTimeAsync(0))
    hook.rerender({ input: B, immediate: 2 })
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(calls.map((c) => c.url)).toEqual([A, B])
    expect(calls[0].signal?.aborted).toBe(true)

    await settle(calls[0])
    expect(hook.result.current.data).toBeUndefined()
    await settle(calls[1])
    expect(hook.result.current.data?.file_id).toBe('bbb222')
  })

  it('checks locally without the backend', () => {
    const { calls } = fakeResolve()
    const hook = setup()
    hook.rerender({ input: 'not a link', immediate: 1 })
    expect(hook.result.current.local.kind).toBe('invalid')
    hook.rerender({ input: 'https://example.com/file/x', immediate: 2 })
    expect(hook.result.current.local.kind).toBe('unsupported')
    expect(calls).toHaveLength(0)
  })
})
