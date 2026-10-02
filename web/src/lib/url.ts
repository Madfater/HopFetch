import type { Provider } from '../api/types'

// - URL handling shared by the input slot: extraction from pasted text, normalization, and
//   matching against provider patterns.
// - `normalizeUrl` mirrors the backend's `normalize_url`, so both sides match the same string.

// - A URL ends at whitespace, quotes, angle brackets or full-width punctuation, which in
//   Chinese text often follows a link with no space.
const URL_IN_TEXT = /https?:\/\/[^\s<>"'`，。、；：！？「」『』（）【】]+/gi
const TRAILING_PUNCTUATION = /[),.;:!?\]}>，。、；：！？）」』】]+$/

export function normalizeUrl(url: string): string {
  const trimmed = url.trim()
  const found = /^([A-Za-z][A-Za-z0-9+.-]*:\/\/)([^/?#]*)(.*)$/s.exec(trimmed)
  if (!found) return trimmed
  return found[1].toLowerCase() + found[2].toLowerCase() + found[3]
}

export function extractUrls(text: string): string[] {
  return [...text.matchAll(URL_IN_TEXT)].map((m) => m[0].replace(TRAILING_PUNCTUATION, ''))
}

export type Extracted = { kind: 'none' } | { kind: 'one'; url: string } | { kind: 'many' }

// - Exactly one URL in pasted text is taken as the input; more than one is reported, so the
//   user knows only one link fits.
export function extractSingleUrl(text: string): Extracted {
  const urls = [...new Set(extractUrls(text))]
  if (urls.length === 0) return { kind: 'none' }
  if (urls.length === 1) return { kind: 'one', url: urls[0] }
  return { kind: 'many' }
}

export function isHttpUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.hostname !== ''
  } catch {
    return false
  }
}

export interface Match {
  provider: Provider
  fileId: string
}

// - Returns the first provider whose pattern matches the normalized URL, with group 1 as the
//   file id, or null.
export function matchProvider(url: string, providers: Provider[]): Match | null {
  const normalized = normalizeUrl(url)
  for (const provider of providers) {
    for (const pattern of provider.patterns) {
      const found = new RegExp(pattern).exec(normalized)
      if (found && found.index === 0) return { provider, fileId: found[1] }
    }
  }
  return null
}
