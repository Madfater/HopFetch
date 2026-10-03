import type { Settings, SettingsChange } from '../api/types'

// - The settings form's draft keeps the text of each number field, so a value being typed is
//   never rewritten under the cursor.
// - LIMITS mirror the backend's checks in downloader/settings_store.py: 1 to 64 connections,
//   1 to 10 simultaneous downloads, parts of at least 20 MiB. Only whole numbers pass, and an
//   out-of-range field gets the backend's own message for that setting.
// - The part size is edited in MiB and sent in bytes. A save sends only the settings that
//   changed, so it never overwrites another user's change to a setting left alone here.

export const MIB = 2 ** 20

export interface Draft {
  connections: string
  maxActive: string
  splitMib: string
  useProxies: boolean
}

export type Field = keyof Draft
export type NumberField = Exclude<Field, 'useProxies'>

export interface Problem {
  key: string
  params: Record<string, number>
}

export const LIMITS: Record<NumberField, { min: number; max?: number }> = {
  connections: { min: 1, max: 64 },
  maxActive: { min: 1, max: 10 },
  splitMib: { min: 20 },
}

const PROBLEMS: Record<NumberField, Problem> = {
  connections: { key: 'errors.invalid_settings_connections', params: { min: 1, max: 64 } },
  maxActive: { key: 'errors.invalid_settings_max_active_jobs', params: { min: 1, max: 10 } },
  splitMib: { key: 'errors.invalid_settings_split_size', params: { min_mib: 20 } },
}

export const NUMBER_FIELDS = Object.keys(LIMITS) as NumberField[]

export function toDraft(settings: Settings): Draft {
  return {
    connections: String(settings.connections),
    maxActive: String(settings.max_active_jobs),
    splitMib: String(Math.round(settings.split_size / MIB)),
    useProxies: settings.use_proxies,
  }
}

// - The number written in `text` with digits only, or null.
export function parseWhole(text: string): number | null {
  const trimmed = text.trim()
  return /^\d+$/.test(trimmed) ? Number(trimmed) : null
}

// - The number fields whose text is not a whole number within limits, in form order.
export function validate(draft: Draft): Partial<Record<NumberField, Problem>> {
  const problems: Partial<Record<NumberField, Problem>> = {}
  for (const field of NUMBER_FIELDS) {
    const value = parseWhole(draft[field])
    const { min, max = Infinity } = LIMITS[field]
    if (value === null || value < min || value > max) problems[field] = PROBLEMS[field]
  }
  return problems
}

// - The fields that differ from the saved settings. Numbers compare by value, so "020" is
//   unchanged from 20; text that is not a number counts as changed.
export function changedFields(draft: Draft, saved: Settings): Field[] {
  const base = toDraft(saved)
  return (['connections', 'maxActive', 'splitMib', 'useProxies'] as Field[]).filter((field) => {
    if (field === 'useProxies') return draft.useProxies !== base.useProxies
    return parseWhole(draft[field]) !== Number(base[field])
  })
}

// - One step up or down from the field's text, kept within the limits. Text that is not a
//   number steps from the minimum.
export function stepValue(field: NumberField, text: string, delta: number): string {
  const { min, max = Infinity } = LIMITS[field]
  const value = parseWhole(text)
  return String(value === null ? min : Math.min(max, Math.max(min, value + delta)))
}

// - The body of PUT /api/settings for the changed fields of a valid draft.
export function toChange(draft: Draft, fields: Field[]): SettingsChange {
  const change: SettingsChange = {}
  if (fields.includes('connections')) change.connections = Number(draft.connections)
  if (fields.includes('maxActive')) change.max_active_jobs = Number(draft.maxActive)
  if (fields.includes('splitMib')) change.split_size = Number(draft.splitMib) * MIB
  if (fields.includes('useProxies')) change.use_proxies = draft.useProxies
  return change
}
