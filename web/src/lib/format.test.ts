import { describe, expect, it } from 'vitest'
import { formatBytes, formatDuration, formatList, formatStorage, pathSegments } from './format'

describe('formatList', () => {
  it('joins names the way the locale does', () => {
    expect(formatList('en', ['Keep2Share', 'MEGA'], 'disjunction')).toBe('Keep2Share or MEGA')
    expect(formatList('en', ['Keep2Share', 'MEGA'], 'conjunction')).toBe('Keep2Share and MEGA')
  })

  it('spaces Latin names from Chinese connectives', () => {
    expect(formatList('zh-Hant-TW', ['Keep2Share', 'MEGA'], 'disjunction')).toBe('Keep2Share 或 MEGA')
    expect(formatList('zh-Hant-TW', ['Keep2Share', 'MEGA'], 'conjunction')).toBe('Keep2Share 和 MEGA')
  })
})

describe('format', () => {
  it('formats durations like the backend formatter', () => {
    expect(formatDuration(750)).toBe('12:30')
    expect(formatDuration(3725)).toBe('1:02:05')
    expect(formatDuration(5)).toBe('0:05')
  })

  it('shows storage in GB below one TB and TB from there', () => {
    expect(formatStorage('en', 512 * 1024 ** 3)).toBe('512 GB')
    expect(formatStorage('en', 3.5 * 1024 ** 4)).toBe('3.50 TB')
  })

  it('formats sizes with the locale', () => {
    expect(formatBytes('en', 1536)).toBe('1.50 KB')
    expect(formatBytes('en', null)).toBe('')
  })
})

describe('pathSegments', () => {
  it('ends each segment at its separator', () => {
    expect(pathSegments('/volume1/downloads/hop')).toEqual(['/', 'volume1/', 'downloads/', 'hop'])
    expect(pathSegments('/data/')).toEqual(['/', 'data/'])
    expect(pathSegments('C:\\Users\\me')).toEqual(['C:\\', 'Users\\', 'me'])
    expect(pathSegments('plain')).toEqual(['plain'])
  })
})
