import type { CodedError, Provider, Resolved, Settings, SettingsChange, Storage, Task } from './types'

// - Typed client for the backend under /api.
// - A non-2xx answer throws ApiError carrying the backend's {code, key, params, message} and any
//   extra fields such as task_id; an unreachable server throws ApiError with code `network`.

export class ApiError extends Error {
  status: number
  error: CodedError
  extra: Record<string, unknown>

  constructor(status: number, error: CodedError, extra: Record<string, unknown> = {}) {
    super(error.message)
    this.status = status
    this.error = error
    this.extra = extra
  }
}

const NETWORK_ERROR: CodedError = { code: 'network', key: 'errors.network', params: {}, message: '' }

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(`/api${path}`, {
      ...init,
      headers: init.body ? { 'Content-Type': 'application/json' } : undefined,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, NETWORK_ERROR)
  }
  if (!resp.ok) {
    let body: Record<string, unknown> = {}
    try {
      body = await resp.json()
    } catch {
      // - Keeps the generic error when the body is not JSON.
    }
    const { code, key, params, message, ...extra } = body
    const error: CodedError =
      typeof code === 'string'
        ? { code, key: String(key ?? `errors.${code}`), params: (params as CodedError['params']) ?? {}, message: String(message ?? '') }
        : { code: 'http_error', key: 'errors.http_error', params: {}, message: '' }
    throw new ApiError(resp.status, error, extra)
  }
  return resp.status === 204 ? (undefined as T) : resp.json()
}

const post = (body?: unknown, signal?: AbortSignal): RequestInit => ({
  method: 'POST',
  body: body === undefined ? undefined : JSON.stringify(body),
  signal,
})

export const api = {
  providers: () => call<Provider[]>('/providers'),
  resolve: (url: string, signal?: AbortSignal) => call<Resolved>('/resolve', post({ url }, signal)),
  tasks: (signal?: AbortSignal) => call<Task[]>('/tasks', { signal }),
  create: (url: string, force = false, useProxy = true) =>
    call<Task>('/tasks', post({ url, force, use_proxy: useProxy })),
  pause: (id: string) => call<Task>(`/tasks/${id}/pause`, post()),
  resume: (id: string) => call<Task>(`/tasks/${id}/resume`, post()),
  cancel: (id: string) => call<Task>(`/tasks/${id}/cancel`, post()),
  retry: (id: string) => call<Task>(`/tasks/${id}/retry`, post()),
  remove: (id: string, deleteFile: boolean) =>
    call<void>(`/tasks/${id}?delete_file=${deleteFile}`, { method: 'DELETE' }),
  clearCompleted: () => call<{ removed: number }>('/tasks/clear-completed', post()),
  storage: () => call<Storage>('/storage'),
  settings: () => call<Settings>('/settings'),
  saveSettings: (change: SettingsChange) =>
    call<Settings>('/settings', { method: 'PUT', body: JSON.stringify(change) }),
  fileUrl: (id: string) => `/api/tasks/${id}/file`,
}
