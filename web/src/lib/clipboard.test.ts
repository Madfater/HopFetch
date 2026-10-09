import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyText } from './clipboard'

// - Fakes a secure context whose Clipboard API refuses the write, and `document.execCommand`,
//   restoring both after each test.

afterEach(() => {
  vi.unstubAllGlobals()
  Reflect.deleteProperty(document, 'execCommand')
  Reflect.deleteProperty(navigator, 'clipboard')
})

describe('copyText', () => {
  it('falls back to the textarea copy when the Clipboard API refuses', async () => {
    vi.stubGlobal('isSecureContext', true)
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const copied: string[] = []
    Object.defineProperty(document, 'execCommand', {
      value: vi.fn(() => {
        copied.push(document.querySelector('textarea')?.value ?? '')
        return true
      }),
      configurable: true,
    })
    expect(await copyText('/volume1/downloads')).toBe(true)
    expect(writeText).toHaveBeenCalledWith('/volume1/downloads')
    expect(copied).toEqual(['/volume1/downloads'])
    expect(document.querySelector('textarea')).toBeNull()
  })
})
