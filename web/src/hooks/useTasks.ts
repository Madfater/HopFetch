import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { PROVIDERS_KEY, TASKS_KEY } from '../lib/tasks'

// - The task list and the provider list, shared by every page.
// - Neither refetches on mount: the event stream keeps the task list current, and every stream
//   (re)connect refetches both. A mount-time refetch would race with events and could put an
//   older snapshot over a newer event.

export function useTasks() {
  return useQuery({ queryKey: TASKS_KEY, queryFn: ({ signal }) => api.tasks(signal), staleTime: Infinity })
}

export function useProviders() {
  return useQuery({ queryKey: PROVIDERS_KEY, queryFn: api.providers, staleTime: Infinity })
}
