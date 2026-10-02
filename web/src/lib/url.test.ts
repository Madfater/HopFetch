import { describe, expect, it } from 'vitest'
import cases from '../../../shared/provider-test-cases.json'
import providers from '../../../shared/providers.json'
import { extractSingleUrl, extractUrls, isHttpUrl, matchProvider, normalizeUrl } from './url'

// - The URL cases in shared/ are the same ones pytest runs against the backend.

describe('matchProvider with the shared cases', () => {
  for (const testCase of cases) {
    it(JSON.stringify(testCase.url), () => {
      const match = isHttpUrl(testCase.url.trim()) ? matchProvider(testCase.url, providers) : null
      expect(match ? { provider: match.provider.id, fileId: match.fileId } : null).toEqual(
        testCase.provider ? { provider: testCase.provider, fileId: testCase.file_id } : null,
      )
    })
  }
})

describe('normalizeUrl', () => {
  it('lowercases scheme and host only and trims', () => {
    expect(normalizeUrl('  HTTPS://K2S.CC/file/AbC/X.zip ')).toBe('https://k2s.cc/file/AbC/X.zip')
  })
})

describe('extracting a URL from pasted text', () => {
  it('finds one URL inside text and drops trailing punctuation', () => {
    expect(extractSingleUrl('看這個 https://k2s.cc/file/abc123/x.rar。謝謝')).toEqual({
      kind: 'one',
      url: 'https://k2s.cc/file/abc123/x.rar',
    })
    expect(extractUrls('(https://k2s.cc/file/abc)')).toEqual(['https://k2s.cc/file/abc'])
  })

  it('treats the same URL twice as one', () => {
    expect(extractSingleUrl('https://k2s.cc/file/a https://k2s.cc/file/a').kind).toBe('one')
  })

  it('reports several URLs', () => {
    expect(extractSingleUrl('https://k2s.cc/file/a\nhttps://k2s.cc/file/b')).toEqual({ kind: 'many' })
  })

  it('reports none in plain text', () => {
    expect(extractSingleUrl('just words')).toEqual({ kind: 'none' })
  })
})
