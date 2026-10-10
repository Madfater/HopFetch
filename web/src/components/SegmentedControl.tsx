import { RadioGroup } from 'radix-ui'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import styles from './SegmentedControl.module.css'

// - One choice out of a few, as segments on a recessed track. It is a radio group: arrow keys
//   move between segments and choose.
// - A raised thumb sits under the chosen segment. Its place is measured from that segment, and
//   measured again whenever a segment changes size, such as after a language change. It first
//   appears in place and slides on later changes.
// - The thumb spans from the track's start to the end of the last segment and is clipped to the
//   chosen one, so it slides by animating its clip, never its size or place. Its span comes from
//   the segments, not the track's scroll width, which the thumb itself would widen.
// - `data-more` marks a track whose segments run past its right edge, and `data-less` one
//   scrolled away from its start, measured on resize and scroll, so each edge can fade to show
//   that the track scrolls that way.
// - `stretch` lets the track fill its container on a phone, sharing the room among the segments.

export interface Segment<T extends string> {
  value: T
  label: ReactNode
  lang?: string
}

interface Props<T extends string> {
  value: T
  options: Segment<T>[]
  onChange: (value: T) => void
  label?: string
  labelledBy?: string
  describedBy?: string
  stretch?: boolean
}

export function SegmentedControl<T extends string>({ value, options, onChange, label, labelledBy, describedBy, stretch }: Props<T>) {
  const track = useRef<HTMLDivElement>(null)
  const [thumb, setThumb] = useState<{ x: number; width: number; span: number } | null>(null)
  const [more, setMore] = useState(false)
  const [less, setLess] = useState(false)

  useLayoutEffect(() => {
    const root = track.current
    if (!root) return
    const measure = () => {
      setMore(root.scrollLeft + root.clientWidth < root.scrollWidth - 1)
      setLess(root.scrollLeft > 1)
      const chosen = root.querySelector<HTMLElement>('[role="radio"][data-state="checked"]')
      if (!chosen) return
      const segments = root.querySelectorAll<HTMLElement>('[role="radio"]')
      const last = segments[segments.length - 1]
      const span = last.offsetLeft + last.offsetWidth
      const next = { x: chosen.offsetLeft, width: chosen.offsetWidth, span }
      setThumb((shown) =>
        shown && shown.x === next.x && shown.width === next.width && shown.span === next.span ? shown : next)
    }
    measure()
    root.addEventListener('scroll', measure, { passive: true })
    if (typeof ResizeObserver === 'undefined') return () => root.removeEventListener('scroll', measure)
    const observer = new ResizeObserver(measure)
    observer.observe(root)
    for (const segment of root.querySelectorAll('[role="radio"]')) observer.observe(segment)
    return () => {
      observer.disconnect()
      root.removeEventListener('scroll', measure)
    }
  }, [value, options.length])

  return (
    <RadioGroup.Root ref={track} className={`${styles.track} ${stretch ? styles.stretch : ''}`} data-more={more || undefined} data-less={less || undefined} value={value} orientation="horizontal" loop
      aria-label={labelledBy ? undefined : label} aria-labelledby={labelledBy} aria-describedby={describedBy}
      onValueChange={(next) => onChange(next as T)}>
      {thumb && (
        <span className={styles.thumb} aria-hidden="true"
          style={{
            width: thumb.span,
            clipPath: `inset(0 ${thumb.span - thumb.x - thumb.width}px 0 ${thumb.x}px round var(--thumb-radius))`,
          }} />
      )}
      {options.map((option) => (
        <RadioGroup.Item key={option.value} value={option.value} className={styles.segment} lang={option.lang}>
          {option.label}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  )
}
