import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SETTLE_MS, useNewIds } from './useNewIds'

afterEach(() => {
  vi.useRealTimers()
})

describe('useNewIds', () => {
  it('treats the first loaded list as known and later ids as new', () => {
    const hook = renderHook(({ ids }) => useNewIds(ids), { initialProps: { ids: ['a', 'b'] as string[] | undefined } })
    expect(hook.result.current('a')).toBe(false)
    hook.rerender({ ids: ['c', 'a', 'b'] })
    expect(hook.result.current('c')).toBe(true)
    expect(hook.result.current('b')).toBe(false)
  })

  it('waits for the list to load before learning the known ids', () => {
    const hook = renderHook(({ ids }) => useNewIds(ids), { initialProps: { ids: undefined as string[] | undefined } })
    expect(hook.result.current('a')).toBe(false)
    hook.rerender({ ids: ['a'] })
    expect(hook.result.current('a')).toBe(false)
    hook.rerender({ ids: ['b', 'a'] })
    expect(hook.result.current('b')).toBe(true)
  })

  it('counts an arrival as known once its flash has had time to end', () => {
    vi.useFakeTimers()
    const hook = renderHook(({ ids }) => useNewIds(ids), { initialProps: { ids: ['a'] } })
    hook.rerender({ ids: ['b', 'a'] })
    act(() => vi.advanceTimersByTime(SETTLE_MS - 1))
    hook.rerender({ ids: ['b', 'a'] })
    expect(hook.result.current('b')).toBe(true)
    act(() => vi.advanceTimersByTime(1))
    expect(hook.result.current('b')).toBe(false)
  })

  it('starts over on a remount', () => {
    const first = renderHook(({ ids }) => useNewIds(ids), { initialProps: { ids: ['a'] } })
    first.rerender({ ids: ['b', 'a'] })
    first.unmount()
    const second = renderHook(() => useNewIds(['b', 'a']))
    expect(second.result.current('b')).toBe(false)
  })
})
