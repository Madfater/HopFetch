import { describe, expect, it } from 'vitest'
import tokens from './tokens.css?raw'

// - WCAG contrast of the color tokens as they are used: text needs 4.5:1, and the parts that
//   identify a control or its state (lamps, the focus ring, field edges, switch and segment
//   faces, the red error edge of a field) need 3:1 against what surrounds them. Dark text sits
//   on the gold primary button and on the lit faces of the state colors.

function hexColors(css: string): Map<string, string> {
  const found = new Map<string, string>()
  for (const [, name, value] of css.matchAll(/--color-([\w-]+):\s*(#[0-9a-f]{6})\b/gi)) found.set(name, value)
  return found
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (high + 0.05) / (low + 0.05)
}

const colors = hexColors(tokens)

function color(name: string): string {
  const value = colors.get(name)
  if (!value) throw new Error(`--color-${name} is not a hex color in tokens.css`)
  return value
}

const SURFACES = ['ground', 'shell', 'panel', 'raised', 'well']

const TEXT: [string, string[]][] = [
  ['text', [...SURFACES, 'selected']],
  ['muted', SURFACES],
  ['active', ['shell']],
  ['failed-text', SURFACES],
  ['on-light', ['accent', 'active', 'done', 'failed']],
]

const PARTS: [string, string[]][] = [
  ['active', SURFACES],
  ['done', SURFACES],
  ['failed', SURFACES],
  ['muted', SURFACES],
  ['field-edge', ['ground', 'panel']],
  ['focus', SURFACES],
  ['accent', ['panel']],
  ['selected', ['well']],
  ['ground', ['accent']],
]

const pairs = (list: [string, string[]][]) => list.flatMap(([fg, backgrounds]) => backgrounds.map((bg) => [fg, bg]))

describe('color tokens', () => {
  it.each(pairs(TEXT))('text %s on %s reaches 4.5:1', (fg, bg) => {
    expect(contrast(color(fg), color(bg))).toBeGreaterThanOrEqual(4.5)
  })

  it.each(pairs(PARTS))('control part %s on %s reaches 3:1', (fg, bg) => {
    expect(contrast(color(fg), color(bg))).toBeGreaterThanOrEqual(3)
  })
})
