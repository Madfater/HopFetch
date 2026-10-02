import type { Status, Task } from '../api/types'

// - Pure helpers over the task list kept in the TanStack Query cache under TASKS_KEY.
// - The list is newest first, the order GET /api/tasks returns.

export const TASKS_KEY = ['tasks'] as const
export const STORAGE_KEY = ['storage'] as const

export const ACTIVE: Status[] = ['queued', 'downloading']

export function isActive(task: Task): boolean {
  return ACTIVE.includes(task.status)
}

// - Replaces the task with the same id, or puts a new one first.
export function upsertTask(list: Task[] | undefined, task: Task): Task[] | undefined {
  if (!list) return list
  const index = list.findIndex((t) => t.id === task.id)
  if (index === -1) return [task, ...list]
  const next = list.slice()
  next[index] = task
  return next
}

export function removeTask(list: Task[] | undefined, id: string): Task[] | undefined {
  return list?.filter((t) => t.id !== id)
}

export type Filter = 'all' | 'active' | 'completed' | 'failed'

export const FILTERS: Filter[] = ['all', 'active', 'completed', 'failed']

export function matchesFilter(task: Task, filter: Filter): boolean {
  switch (filter) {
    case 'all':
      return true
    case 'active':
      return task.status === 'queued' || task.status === 'downloading' || task.status === 'paused'
    case 'completed':
      return task.status === 'completed'
    case 'failed':
      return task.status === 'failed' || task.status === 'canceled'
  }
}

// - Status changes worth a toast: a task that reached completed or failed since the last copy.
export type Finished = { task: Task; outcome: 'completed' | 'failed' }

export function finishedSince(previous: Task | undefined, next: Task): Finished | null {
  if (!previous || previous.status === next.status) return null
  if (next.status === 'completed' || next.status === 'failed') return { task: next, outcome: next.status }
  return null
}
