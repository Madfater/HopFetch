import { describe, expect, it } from 'vitest'
import cases from '../../../shared/provider-test-cases.json'
import providers from '../../../shared/providers.json'
import { BATCH_LIMIT, extractBatch, extractSingleUrl, extractUrls, isHttpUrl, matchProvider, normalizeUrl } from './url'

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

describe('extracting a batch from pasted text', () => {
  const MEGA = 'https://mega.nz/file/AbCd1234#' + 'k'.repeat(43)

  it('keeps supported links in order and counts the others', () => {
    const text = [
      'Part 1 https://k2s.cc/file/aaa111/x.part1.rar',
      'cover https://img.example.com/cover.jpg',
      'Part 2：https://keep2share.cc/file/bbb222/x.part2.rar，',
      `mirror ${MEGA}`,
      'thread https://forum.example.com/t/42',
    ].join('\n')
    const batch = extractBatch(text, providers)
    expect(batch.links.map((link) => [link.key, link.url])).toEqual([
      ['k2s:aaa111', 'https://k2s.cc/file/aaa111/x.part1.rar'],
      ['k2s:bbb222', 'https://keep2share.cc/file/bbb222/x.part2.rar'],
      ['mega:AbCd1234', MEGA],
    ])
    expect(batch.ignored).toBe(2)
    expect(batch.dropped).toBe(0)
  })

  it('keeps the query of a Google Drive link and counts its link forms as one file', () => {
    const id = '1l_5RK28JRL19wpT22B-DY9We3TVXnnQQ'
    const text = `a https://drive.google.com/uc?export=download&id=${id} b https://drive.google.com/file/d/${id}/view`
    const batch = extractBatch(text, providers)
    expect(batch.links.map((link) => [link.key, link.url])).toEqual([
      [`gdrive:${id}`, `https://drive.google.com/uc?export=download&id=${id}`],
    ])
  })

  it('counts one file once across host aliases', () => {
    const batch = extractBatch('https://k2s.cc/file/aaa111/x.rar https://KEEP2SHARE.CC/file/aaa111', providers)
    expect(batch.links.map((link) => link.key)).toEqual(['k2s:aaa111'])
  })

  it('keeps the first BATCH_LIMIT links', () => {
    const text = Array.from({ length: BATCH_LIMIT + 3 }, (_, i) => `https://k2s.cc/file/f${i}`).join(' ')
    const batch = extractBatch(text, providers)
    expect(batch.links).toHaveLength(BATCH_LIMIT)
    expect(batch.links[0].key).toBe('k2s:f0')
    expect(batch.dropped).toBe(3)
  })
})
