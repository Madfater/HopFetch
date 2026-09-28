// - Typed client for the FastAPI backend under /api.
// - Every call throws ApiError with the server's `detail` message on a non-2xx answer.

export type JobState =
  | 'queued'
  | 'resolving'
  | 'preparing'
  | 'solving_captcha'
  | 'awaiting_captcha'
  | 'waiting'
  | 'generating_links'
  | 'downloading'
  | 'assembling'
  | 'verifying'
  | 'completed'
  | 'failed'
  | 'paused'

export interface Job {
  id: string
  url: string
  provider: string
  file_id: string
  connections: number
  split_size: number
  filename: string | null
  size: number | null
  state: JobState
  message: string
  error: string | null
  created_at: number
  updated_at: number
  links_count: number
  done_bytes: number
  parts_total: number
  parts_done: number
  active_connections: number
  speed: number
  output_path: string | null
  verified: string | null
  captcha_attempts: number
}

export interface Provider {
  name: string
  label: string
  hosts: string[]
}

export type Resolved =
  | { supported: true; provider: string; label: string; file_id: string }
  | { supported: false; error: string }

export interface NewJob {
  url: string
  filename?: string
  connections: number
  split_size: string
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!resp.ok) {
    let message = `Request failed (${resp.status})`
    try {
      const body = await resp.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      // - Keeps the generic message when the body is not JSON.
    }
    throw new ApiError(resp.status, message)
  }
  return resp.status === 204 ? (undefined as T) : resp.json()
}

export const api = {
  providers: () => call<Provider[]>('/providers'),
  resolve: (url: string) => call<Resolved>('/resolve', { method: 'POST', body: JSON.stringify({ url }) }),
  jobs: () => call<Job[]>('/jobs'),
  create: (job: NewJob) => call<Job>('/jobs', { method: 'POST', body: JSON.stringify(job) }),
  pause: (id: string) => call<Job>(`/jobs/${id}/pause`, { method: 'POST' }),
  resume: (id: string) => call<Job>(`/jobs/${id}/resume`, { method: 'POST' }),
  remove: (id: string) => call<void>(`/jobs/${id}`, { method: 'DELETE' }),
  captcha: (id: string, answer: string) =>
    call<Job>(`/jobs/${id}/captcha`, { method: 'POST', body: JSON.stringify({ answer }) }),
  captchaUrl: (id: string, nonce: number) => `/api/jobs/${id}/captcha?n=${nonce}`,
  fileUrl: (id: string) => `/api/jobs/${id}/file`,
}
