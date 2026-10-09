// - Locale-aware formatting of sizes, speeds, durations and percentages with Intl.
// - Sizes use powers of 1024 and the units B, KB, MB, GB, TB, the convention NAS tools show.

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

function number(locale: string, value: number, digits: number): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value)
}

export function formatBytes(locale: string, bytes: number | null | undefined): string {
  if (bytes == null) return ''
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  const digits = unit === 0 ? 0 : value < 10 ? 2 : value < 100 ? 1 : 0
  return `${number(locale, value, digits)} ${UNITS[unit]}`
}

// - Free space in the navigation bar: GB below one TB, TB from there up.
export function formatStorage(locale: string, bytes: number): string {
  const tb = bytes / 1024 ** 4
  if (tb >= 1) return `${number(locale, tb, tb < 10 ? 2 : 1)} TB`
  const gb = bytes / 1024 ** 3
  return `${number(locale, gb, gb < 10 ? 1 : 0)} GB`
}

export function formatSpeed(locale: string, bytesPerSecond: number): string {
  return `${formatBytes(locale, bytesPerSecond)}/s`
}

// - Whole seconds as `m:ss`, or `h:mm:ss` from one hour up; the backend's `duration` formatter
//   produces the same text.
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = String(total % 60).padStart(2, '0')
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`
}

export function formatPercent(locale: string, ratio: number): string {
  return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(ratio)
}

// - Splits a filesystem path after each separator, so the separators stay at line ends when
//   the path wraps.
export function pathSegments(path: string): string[] {
  return path.match(/[^/\\]*[/\\]|[^/\\]+$/g) ?? [path]
}

// - A list of names joined the way the locale joins lists, for example "Keep2Share or MEGA".
// - Chinese list patterns put no space around their connectives, so a space is added wherever
//   a Latin letter or digit meets a Han character, the usual spacing in mixed text.
export function formatList(locale: string, names: string[], type: 'conjunction' | 'disjunction'): string {
  return new Intl.ListFormat(locale, { type })
    .format(names)
    .replace(/([A-Za-z0-9])(\p{Script=Han})/gu, '$1 $2')
    .replace(/(\p{Script=Han})([A-Za-z0-9])/gu, '$1 $2')
}
