import { describe, expect, it } from 'vitest'
import type { Settings } from '../api/types'
import { changedFields, MIB, parseWhole, stepValue, toChange, toDraft, validate, type Draft } from './settings'

const SAVED: Settings = {
  connections: 20, split_size: 20 * MIB, use_proxies: true, max_active_jobs: 2, download_root: '/downloads',
}

const draft = (change: Partial<Draft> = {}): Draft => ({ ...toDraft(SAVED), ...change })

describe('settings draft', () => {
  it('shows the part size in MiB', () => {
    expect(toDraft({ ...SAVED, split_size: 64 * MIB }).splitMib).toBe('64')
  })

  it('reads only whole numbers', () => {
    expect(parseWhole(' 32 ')).toBe(32)
    for (const text of ['', '2.5', '-1', '2e1', 'abc']) expect(parseWhole(text)).toBeNull()
  })

  it('accepts the limits the backend accepts', () => {
    expect(validate(draft({ connections: '1', maxActive: '10', splitMib: '20' }))).toEqual({})
    expect(validate(draft({ connections: '64', maxActive: '1', splitMib: '4096' }))).toEqual({})
  })

  it('names each value out of range with the backend message', () => {
    const problems = validate(draft({ connections: '65', maxActive: '0', splitMib: '19' }))
    expect(problems.connections).toEqual({ key: 'errors.invalid_settings_connections', params: { min: 1, max: 64 } })
    expect(problems.maxActive).toEqual({ key: 'errors.invalid_settings_max_active_jobs', params: { min: 1, max: 10 } })
    expect(problems.splitMib).toEqual({ key: 'errors.invalid_settings_split_size', params: { min_mib: 20 } })
  })

  it('rejects empty and fractional values', () => {
    expect(Object.keys(validate(draft({ connections: '', splitMib: '20.5' })))).toEqual(['connections', 'splitMib'])
  })

  it('counts changed fields by value', () => {
    expect(changedFields(draft(), SAVED)).toEqual([])
    expect(changedFields(draft({ connections: '020' }), SAVED)).toEqual([])
    expect(changedFields(draft({ connections: '32', useProxies: false }), SAVED)).toEqual(['connections', 'useProxies'])
    expect(changedFields(draft({ maxActive: '' }), SAVED)).toEqual(['maxActive'])
  })

  it('steps within the limits', () => {
    expect(stepValue('connections', '20', 1)).toBe('21')
    expect(stepValue('connections', '64', 1)).toBe('64')
    expect(stepValue('maxActive', '1', -1)).toBe('1')
    expect(stepValue('splitMib', '5', 1)).toBe('20')
    expect(stepValue('connections', '', 1)).toBe('1')
  })

  it('sends only the changed settings, with the part size in bytes', () => {
    expect(toChange(draft({ splitMib: '32', useProxies: false }), ['splitMib', 'useProxies']))
      .toEqual({ split_size: 32 * MIB, use_proxies: false })
    expect(toChange(draft({ connections: '8', maxActive: '3' }), ['connections', 'maxActive']))
      .toEqual({ connections: 8, max_active_jobs: 3 })
  })
})
