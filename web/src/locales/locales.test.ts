import { describe, expect, it } from 'vitest'
import sharedZh from '../../../shared/i18n/zh-Hant-TW.json'
import en from './en.json'
import zh from './zh-Hant-TW.json'

// - Both interface catalogs must have the same keys and the same placeholders, with i18next
//   plural variants (`_one`, `_other`) folded into their base key.

const PLURAL = /_(zero|one|two|few|many|other)$/
const PLACEHOLDER = /\{\{\s*(\w+)\s*(?:,\s*\w+\s*)?\}\}/g

function flatten(node: unknown, prefix = '', out = new Map<string, Set<string>>()) {
  if (typeof node === 'string') {
    const key = prefix.replace(PLURAL, '')
    const names = out.get(key) ?? new Set<string>()
    for (const found of node.matchAll(PLACEHOLDER)) names.add(found[1])
    out.set(key, names)
  } else if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) flatten(v, prefix ? `${prefix}.${k}` : k, out)
  }
  return out
}

function asObject(map: Map<string, Set<string>>) {
  return Object.fromEntries([...map].map(([k, v]) => [k, [...v].sort()]))
}

describe('interface catalogs', () => {
  it('share keys and placeholders', () => {
    expect(asObject(flatten(en))).toEqual(asObject(flatten(zh)))
  })

  it('do not redefine backend keys from shared/i18n', () => {
    const ui = flatten(zh)
    const shared = flatten(sharedZh)
    expect([...ui.keys()].filter((key) => shared.has(key))).toEqual([])
  })
})
