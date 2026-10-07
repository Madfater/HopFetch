import type { TFunction } from 'i18next'
import { ApiError } from '../api/client'
import type { BatchItem } from '../hooks/useBatch'
import { errorText } from './messages'

// - What a pasted batch can do: each row's state, the files that can start, the space they need
//   together (the backend's `required_bytes`, which counts part files too), and whether that
//   fits in the free space.
// - A row is skipped when its file cannot start as a plain download: it is already in the list,
//   was downloaded, failed or was canceled before, has no size, or its lookup failed. Skipping
//   an earlier task is calm; a failed lookup is an error.
// - Once the batch was started, each started row shows its outcome instead.

export type Outcome = { kind: 'started' } | { kind: 'failed'; text: string }

export type RowState =
  | { kind: 'checking' }
  | { kind: 'ready' }
  | { kind: 'skipped'; text: string; error: boolean }
  | Outcome

export interface BatchRow {
  item: BatchItem
  state: RowState
}

export interface BatchView {
  rows: BatchRow[]
  ready: BatchItem[]
  checking: number
  needed: number
  short: number
  started: boolean
  canStart: boolean
  enterStarts: boolean
}

const UNFINISHED = new Set(['queued', 'downloading', 'paused'])

function lookupState(t: TFunction, item: BatchItem): RowState {
  if (item.pending) return { kind: 'checking' }
  if (item.error || !item.data) {
    const text = item.error instanceof ApiError ? errorText(t, item.error.error) : t('errors.unknown')
    return { kind: 'skipped', text, error: true }
  }
  const { duplicate, size } = item.data
  if (duplicate && UNFINISHED.has(duplicate.status)) return { kind: 'skipped', text: t('preview.duplicateActive'), error: false }
  if (duplicate?.status === 'completed') return { kind: 'skipped', text: t('preview.duplicateCompleted'), error: false }
  if (duplicate) return { kind: 'skipped', text: t('preview.duplicateFailed'), error: false }
  if (size == null) return { kind: 'skipped', text: t('preview.sizeUnknownHint'), error: true }
  return { kind: 'ready' }
}

export function batchView(t: TFunction, items: BatchItem[], outcomes: Map<string, Outcome>, free: number): BatchView {
  const looked = items.map((item) => ({ item, state: lookupState(t, item) }))
  const ready = looked.filter((row) => row.state.kind === 'ready').map((row) => row.item)
  const checking = looked.filter((row) => row.state.kind === 'checking').length
  const needed = ready.reduce((sum, item) => sum + (item.data?.required_bytes ?? 0), 0)
  const short = Math.max(0, needed - free)
  const started = outcomes.size > 0
  const canStart = !started && checking === 0 && ready.length > 0 && short === 0
  return {
    rows: looked.map((row) => ({ item: row.item, state: outcomes.get(row.item.link.key) ?? row.state })),
    ready,
    checking,
    needed,
    short,
    started,
    canStart,
    enterStarts: canStart && ready.length === items.length,
  }
}
