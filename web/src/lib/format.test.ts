import { describe, expect, it } from 'vitest'
import { formatBytes, formatDuration, formatStorage } from './format'

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
