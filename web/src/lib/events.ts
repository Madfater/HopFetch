import type { QueryClient } from '@tanstack/react-query'
import type { Storage, Task } from '../api/types'
import { finishedSince, removeTask, STORAGE_KEY, TASKS_KEY, upsertTask, type Finished } from './tasks'

// - The single server-sent event stream of the app, feeding the TanStack Query cache.
// - Every time the stream opens, including after a reconnect, the task list and storage are
//   refetched, which fills in whatever happened while it was down.
// - A browser reconnects by itself after a network error. When the stream is closed for good,
//   for example after an HTTP error, it is reopened after RECONNECT_MS.

export const RECONNECT_MS = 3000

export interface EventHandlers {
  onFinished?: (finished: Finished) => void
  onConnection?: (connected: boolean) => void
}

export function applyEvent(client: QueryClient, type: string, data: unknown, handlers: EventHandlers = {}): void {
  if (type === 'task') {
    const task = data as Task
    const previous = client.getQueryData<Task[]>(TASKS_KEY)?.find((t) => t.id === task.id)
    client.setQueryData<Task[]>(TASKS_KEY, (list) => upsertTask(list, task))
    const finished = finishedSince(previous, task)
    if (finished) handlers.onFinished?.(finished)
  } else if (type === 'task_removed') {
    client.setQueryData<Task[]>(TASKS_KEY, (list) => removeTask(list, (data as { id: string }).id))
  } else if (type === 'storage') {
    client.setQueryData<Storage>(STORAGE_KEY, data as Storage)
  }
}

export function connectEvents(client: QueryClient, handlers: EventHandlers = {}, url = '/api/events'): () => void {
  let source: EventSource | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let stopped = false

  const open = () => {
    source = new EventSource(url)
    source.onopen = () => {
      handlers.onConnection?.(true)
      void client.invalidateQueries({ queryKey: TASKS_KEY })
      void client.invalidateQueries({ queryKey: STORAGE_KEY })
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
        applyEvent(client, type, JSON.parse((event as MessageEvent).data), handlers)
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
