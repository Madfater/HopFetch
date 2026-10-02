import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { Task } from '../api/types'
import { applyEvent } from './events'
import { STORAGE_KEY, TASKS_KEY } from './tasks'

function task(id: string, change: Partial<Task> = {}): Task {
  return {
    id, provider: 'k2s', file_id: id, file_name: `${id}.bin`, size: 100, bytes_done: 0, speed: 0, eta: null,
    status: 'queued', phase: null, message_key: null, message_params: {}, message: '', resumable: true,
    file_exists: false, error: null, verified: null, created_at: 1, completed_at: null, ...change,
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
