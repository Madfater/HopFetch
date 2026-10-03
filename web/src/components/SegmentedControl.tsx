import { RadioGroup } from 'radix-ui'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import styles from './SegmentedControl.module.css'

// - One choice out of a few, as segments on a recessed track. It is a radio group: arrow keys
//   move between segments and choose.
// - A raised thumb sits under the chosen segment. Its place is measured from that segment, and
//   measured again whenever a segment changes size, such as after a language change. It first
//   appears in place and slides on later changes.

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
}

export function SegmentedControl<T extends string>({ value, options, onChange, label, labelledBy }: Props<T>) {
  const track = useRef<HTMLDivElement>(null)
  const [thumb, setThumb] = useState<{ x: number; width: number } | null>(null)

  useLayoutEffect(() => {
    const root = track.current
    if (!root) return
    const measure = () => {
      const chosen = root.querySelector<HTMLElement>('[role="radio"][data-state="checked"]')
      if (!chosen) return
      const next = { x: chosen.offsetLeft, width: chosen.offsetWidth }
      setThumb((shown) => (shown && shown.x === next.x && shown.width === next.width ? shown : next))
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    for (const segment of root.querySelectorAll('[role="radio"]')) observer.observe(segment)
    return () => observer.disconnect()
  }, [value, options.length])

  return (
    <RadioGroup.Root ref={track} className={styles.track} value={value} orientation="horizontal" loop
      aria-label={labelledBy ? undefined : label} aria-labelledby={labelledBy}
      onValueChange={(next) => onChange(next as T)}>
      {thumb && (
        <span className={styles.thumb} aria-hidden="true"
          style={{ transform: `translateX(${thumb.x}px)`, width: thumb.width }} />
      )}
      {options.map((option) => (
        <RadioGroup.Item key={option.value} value={option.value} className={styles.segment} lang={option.lang}>
          {option.label}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  )
}
