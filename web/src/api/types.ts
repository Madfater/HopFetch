// - Shapes of the backend API under /api, as documented in docs/refactor-spec.md.

export type Status = 'queued' | 'downloading' | 'paused' | 'completed' | 'failed' | 'canceled'

export type Phase = 'resolving' | 'captcha' | 'waiting' | 'links' | 'downloading' | 'assembling' | 'verifying'

export type Params = Record<string, string | number>

export interface CodedError {
  code: string
  key: string
  params: Params
  message: string
}

export interface Task {
  id: string
  provider: string
  file_id: string
  file_name: string | null
  size: number | null
  bytes_done: number
  speed: number
  eta: number | null
  status: Status
  phase: Phase | null
  message_key: string | null
  message_params: Params
  message: string
  resumable: boolean
  file_exists: boolean
  error: CodedError | null
  verified: 'ok' | 'corrupt' | null
  created_at: number
  completed_at: number | null
}

export interface Provider {
  id: string
  name: string
  icon: string
  patterns: string[]
}

export interface Resolved {
  provider: string
  file_id: string
  file_name: string
  size: number | null
  resumable: boolean
  duplicate: { task_id: string; status: Status } | null
  free_bytes: number
  required_bytes: number | null
}

export interface Storage {
  free_bytes: number
  total_bytes: number
}

export interface Settings {
  connections: number
  split_size: number
  use_proxies: boolean
  max_active_jobs: number
  download_root: string
}

export type SettingsChange = Partial<Omit<Settings, 'download_root'>>
