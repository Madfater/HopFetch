import type { QueryClient } from '@tanstack/react-query'
import type { Storage, Task } from '../api/types'
import { finishedSince, PROVIDERS_KEY, removeTask, RESOLVE_KEY, STORAGE_KEY, TASKS_KEY, upsertTask, type Finished } from './tasks'

// - The single server-sent event stream of the app, feeding the TanStack Query cache.
// - Every time the stream opens, including after a reconnect, the task list, storage and
//   provider list are refetched, which fills in whatever happened while it was down. Events that arrive during
//   that fetch are applied at once and applied again over its result, so the older snapshot
//   never undoes them.
// - A browser reconnects by itself after a network error. When the stream is closed for good,
//   for example after an HTTP error, it is reopened after RECONNECT_MS.

export const RECONNECT_MS = 3000

export interface EventHandlers {
  onFinished?: (finished: Finished) => void
  onConnection?: (connected: boolean) => void
}

// - A task that changes status or leaves the list invalidates resolve answers, whose
//   `duplicate` field may name it; progress-only updates leave them alone.
export function applyEvent(client: QueryClient, type: string, data: unknown, handlers: EventHandlers = {}): void {
  if (type === 'task') {
    const task = data as Task
    const previous = client.getQueryData<Task[]>(TASKS_KEY)?.find((t) => t.id === task.id)
    client.setQueryData<Task[]>(TASKS_KEY, (list) => upsertTask(list, task))
    if (previous?.status !== task.status) void client.invalidateQueries({ queryKey: RESOLVE_KEY })
    const finished = finishedSince(previous, task)
    if (finished) handlers.onFinished?.(finished)
  } else if (type === 'task_removed') {
    client.setQueryData<Task[]>(TASKS_KEY, (list) => removeTask(list, (data as { id: string }).id))
    void client.invalidateQueries({ queryKey: RESOLVE_KEY })
  } else if (type === 'storage') {
    client.setQueryData<Storage>(STORAGE_KEY, data as Storage)
  }
}

// - Cancels any task-list fetch already in flight, whose snapshot may predate the stream,
//   refetches, then replays the events received meanwhile over the new list.
export async function resync(client: QueryClient, fetchTasks: () => Promise<Task[]>, buffer: [string, unknown][]) {
  try {
    await client.cancelQueries({ queryKey: TASKS_KEY })
    await client.fetchQuery({ queryKey: TASKS_KEY, queryFn: fetchTasks, staleTime: 0 })
  } catch {
    // - The list stays as it was; the stream's own error handling reconnects.
  }
  for (const [type, data] of buffer.splice(0)) applyEvent(client, type, data)
}

export function connectEvents(
  client: QueryClient,
  fetchTasks: () => Promise<Task[]>,
  handlers: EventHandlers = {},
  url = '/api/events',
): () => void {
  let source: EventSource | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let stopped = false
  let buffer: [string, unknown][] | null = null

  const open = () => {
    source = new EventSource(url)
    source.onopen = () => {
      handlers.onConnection?.(true)
      const pending: [string, unknown][] = []
      buffer = pending
      void resync(client, fetchTasks, pending).finally(() => {
        if (buffer === pending) buffer = null
      })
      void client.invalidateQueries({ queryKey: STORAGE_KEY })
      void client.invalidateQueries({ queryKey: PROVIDERS_KEY })
    }
    source.onerror = () => {
      handlers.onConnection?.(false)
      if (source?.readyState === EventSource.CLOSED && !stopped) {
        source.close()
        timer = setTimeout(open, RECONNECT_MS)
      }
    }
    for (const type of ['task', 'task_removed', 'storage']) {
      source.addEventListener(type, (event) => {
        const data = JSON.parse((event as MessageEvent).data)
        applyEvent(client, type, data, handlers)
        buffer?.push([type, data])
      })
    }
  }

  open()
  return () => {
    stopped = true
    clearTimeout(timer)
    source?.close()
  }
}
