import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { Task } from '../api/types'
import { applyEvent, resync } from './events'
import { RESOLVE_KEY, STORAGE_KEY, TASKS_KEY } from './tasks'

function task(id: string, change: Partial<Task> = {}): Task {
  return {
    id, provider: 'k2s', file_id: id, file_name: `${id}.bin`, size: 100, bytes_done: 0, speed: 0, eta: null,
    status: 'queued', phase: null, message_key: null, message_params: {}, message: '', resumable: true,
    notice_key: null, file_exists: false, error: null, verified: null, created_at: 1, updated_at: 1,
    completed_at: null, ...change,
  }
}

describe('applyEvent', () => {
  it('replaces a known task in place and adds a new one first', () => {
    const client = new QueryClient()
    client.setQueryData(TASKS_KEY, [task('a'), task('b')])
    applyEvent(client, 'task', task('b', { status: 'downloading', bytes_done: 40 }))
    applyEvent(client, 'task', task('c'))
    const list = client.getQueryData<Task[]>(TASKS_KEY)!
    expect(list.map((t) => t.id)).toEqual(['c', 'a', 'b'])
    expect(list[2].bytes_done).toBe(40)
  })

  it('removes a task on task_removed', () => {
    const client = new QueryClient()
    client.setQueryData(TASKS_KEY, [task('a'), task('b')])
    applyEvent(client, 'task_removed', { id: 'a' })
    expect(client.getQueryData<Task[]>(TASKS_KEY)!.map((t) => t.id)).toEqual(['b'])
  })

  it('leaves the cache empty until the list has been fetched', () => {
    const client = new QueryClient()
    applyEvent(client, 'task', task('a'))
    expect(client.getQueryData(TASKS_KEY)).toBeUndefined()
  })

  it('stores storage events', () => {
    const client = new QueryClient()
    applyEvent(client, 'storage', { free_bytes: 5, total_bytes: 9 })
    expect(client.getQueryData(STORAGE_KEY)).toEqual({ free_bytes: 5, total_bytes: 9 })
  })

  it('reports a task that just completed or failed, once', () => {
    const client = new QueryClient()
    const onFinished = vi.fn()
    client.setQueryData(TASKS_KEY, [task('a', { status: 'downloading' })])
    applyEvent(client, 'task', task('a', { status: 'completed' }), { onFinished })
    applyEvent(client, 'task', task('a', { status: 'completed' }), { onFinished })
    expect(onFinished).toHaveBeenCalledTimes(1)
    expect(onFinished.mock.calls[0][0].outcome).toBe('completed')
  })
})

describe('resync', () => {
  it('replays events received during the refetch over its older snapshot', async () => {
    const client = new QueryClient()
    client.setQueryData(TASKS_KEY, [task('a', { status: 'downloading' })])
    let finishFetch: ((list: Task[]) => void) | null = null
    const fetchTasks = () => new Promise<Task[]>((resolve) => (finishFetch = resolve))
    const buffer: [string, unknown][] = []
    const done = resync(client, fetchTasks, buffer)

    const completed = task('a', { status: 'completed' })
    applyEvent(client, 'task', completed)
    buffer.push(['task', completed])
    applyEvent(client, 'task_removed', { id: 'b' })
    buffer.push(['task_removed', { id: 'b' }])

    await vi.waitFor(() => expect(finishFetch).not.toBeNull())
    finishFetch!([task('a', { status: 'downloading' }), task('b')])
    await done
    const list = client.getQueryData<Task[]>(TASKS_KEY)!
    expect(list.map((t) => [t.id, t.status])).toEqual([['a', 'completed']])
    expect(buffer).toEqual([])
  })
})

describe('resync with a fetch already in flight', () => {
  it('cancels the older fetch so its snapshot cannot land after the replay', async () => {
    const client = new QueryClient()
    let finishOld: (list: Task[]) => void = () => {}
    const old = client
      .fetchQuery({ queryKey: TASKS_KEY, queryFn: () => new Promise<Task[]>((resolve) => (finishOld = resolve)) })
      .catch(() => null)
    const buffer: [string, unknown][] = [['task', task('a', { status: 'completed' })]]
    await resync(client, async () => [task('a', { status: 'downloading' })], buffer)
    finishOld([task('a', { status: 'queued' })])
    await old
    expect(client.getQueryData<Task[]>(TASKS_KEY)!.map((t) => t.status)).toEqual(['completed'])
  })
})

describe('resolve answers', () => {
  it('are invalidated by status changes and removals, not by progress', () => {
    const client = new QueryClient()
    const spy = vi.spyOn(client, 'invalidateQueries')
    client.setQueryData(TASKS_KEY, [task('a', { status: 'downloading' })])
    applyEvent(client, 'task', task('a', { status: 'downloading', bytes_done: 50 }))
    expect(spy).not.toHaveBeenCalled()
    applyEvent(client, 'task', task('a', { status: 'failed' }))
    applyEvent(client, 'task_removed', { id: 'a' })
    expect(spy.mock.calls.map((call) => call[0]?.queryKey)).toEqual([RESOLVE_KEY, RESOLVE_KEY])
  })
})

describe('newest copy wins', () => {
  it('ignores a copy older than the cached one', () => {
    const client = new QueryClient()
    client.setQueryData(TASKS_KEY, [task('a', { status: 'paused', updated_at: 5 })])
    applyEvent(client, 'task', task('a', { status: 'downloading', updated_at: 4 }))
    expect(client.getQueryData<Task[]>(TASKS_KEY)![0].status).toBe('paused')
    applyEvent(client, 'task', task('a', { status: 'queued', updated_at: 6 }))
    expect(client.getQueryData<Task[]>(TASKS_KEY)![0].status).toBe('queued')
  })
})

describe('resync retries', () => {
  it('tries a failed fetch again until it succeeds', async () => {
    const client = new QueryClient()
    let calls = 0
    const fetchTasks = async () => {
      calls += 1
      if (calls < 3) throw new Error('down')
      return [task('a')]
    }
    await resync(client, fetchTasks, [], () => false, 1)
    expect(calls).toBe(3)
    expect(client.getQueryData<Task[]>(TASKS_KEY)!.map((t) => t.id)).toEqual(['a'])
  })

  it('stops trying once the stream is gone', async () => {
    const client = new QueryClient()
    let calls = 0
    let stop = false
    const fetchTasks = async () => {
      calls += 1
      stop = true
      throw new Error('down')
    }
    await resync(client, fetchTasks, [], () => stop, 1)
    expect(calls).toBe(1)
  })
})
