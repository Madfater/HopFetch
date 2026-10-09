import type { Status, Task } from '../api/types'

// - Pure helpers over the task list kept in the TanStack Query cache under TASKS_KEY.
// - The list is newest first, the order GET /api/tasks returns.

export const TASKS_KEY = ['tasks'] as const
export const STORAGE_KEY = ['storage'] as const
export const PROVIDERS_KEY = ['providers'] as const

// - Every /api/resolve answer lives under this key. Answers carry a `duplicate` status, so they
//   are invalidated whenever a task changes status or leaves the list.
export const RESOLVE_KEY = ['resolve'] as const

export const ACTIVE: Status[] = ['queued', 'downloading']

export function isActive(task: Task): boolean {
  return ACTIVE.includes(task.status)
}

// - A failed task whose error a retry can fix is the one state that waits on the user; canceled
//   tasks were their choice.
// - The backend sets `retryable`; the frontend keeps no list of error keys of its own.
export function needsAttention(task: Task): boolean {
  return task.status === 'failed' && task.retryable
}

// - A failed task that no retry can fix, such as a deleted or private file: its own outcome,
//   "cannot be downloaded". It needs nothing from the user but deleting, so it stays out of the
//   failed count, and only the All filter shows it, as with canceled tasks.
export function isUnfixable(task: Task): boolean {
  return task.status === 'failed' && !task.retryable
}

// - Replaces the task with the same id, or puts a new one first.
// - A copy older than the one held, by `updated_at`, is ignored: an action's HTTP answer can
//   arrive after the event the action caused.
export function upsertTask(list: Task[] | undefined, task: Task): Task[] | undefined {
  if (!list) return list
  const index = list.findIndex((t) => t.id === task.id)
  if (index === -1) return [task, ...list]
  if (list[index].updated_at > task.updated_at) return list
  const next = list.slice()
  next[index] = task
  return next
}

export function removeTask(list: Task[] | undefined, id: string): Task[] | undefined {
  return list?.filter((t) => t.id !== id)
}

export type Filter = 'all' | 'active' | 'completed' | 'failed'

export const FILTERS: Filter[] = ['all', 'active', 'completed', 'failed']

export function parseFilter(value: string | null): Filter | null {
  return FILTERS.find((filter) => filter === value) ?? null
}

export function matchesFilter(task: Task, filter: Filter): boolean {
  switch (filter) {
    case 'all':
      return true
    case 'active':
      return task.status === 'queued' || task.status === 'downloading' || task.status === 'paused'
    case 'completed':
      return task.status === 'completed'
    case 'failed':
      return needsAttention(task)
  }
}

// - Status changes worth a toast: a task that reached completed or failed since the last copy.
//   A failed task that no retry can fix has its own outcome, `unfixable`.
export type Finished = { task: Task; outcome: 'completed' | 'failed' | 'unfixable' }

export function finishedSince(previous: Task | undefined, next: Task): Finished | null {
  if (!previous || previous.status === next.status) return null
  if (next.status === 'completed') return { task: next, outcome: 'completed' }
  if (next.status === 'failed') return { task: next, outcome: isUnfixable(next) ? 'unfixable' : 'failed' }
  return null
}
