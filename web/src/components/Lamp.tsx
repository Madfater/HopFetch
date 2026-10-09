import { useState } from 'react'
import type { Status } from '../api/types'
import styles from './Lamp.module.css'

// - An indicator light. Color is never the only signal: callers always put text beside it.
// - A solid active, done or failed lamp is lit; active and failed lamps glow, done lamps do not.
//   `pulse` makes a lit lamp's glow breathe, for work in progress.
// - A lamp that changes color or fill after its first render blinks once, so the change is
//   seen. The element is remounted under a new key, which replays the blink animation.

export type LampColor = 'off' | 'active' | 'done' | 'failed' | 'idle'

const LIT: LampColor[] = ['active', 'done', 'failed']

interface Props {
  color: LampColor
  hollow?: boolean
  pulse?: boolean
}

export function Lamp({ color, hollow = false, pulse = false }: Props) {
  const look = `${color} ${hollow}`
  const [shown, setShown] = useState(look)
  const [blinks, setBlinks] = useState(0)
  if (look !== shown) {
    setShown(look)
    setBlinks((n) => n + 1)
  }
  const lit = !hollow && LIT.includes(color)
  const classes = [styles.lamp, styles[color], hollow && styles.hollow, lit && styles.lit, lit && pulse && styles.pulse,
    blinks > 0 && styles.blink]
  return <span key={blinks} aria-hidden="true" className={classes.filter(Boolean).join(' ')} />
}

const STATUS_LAMP: Record<Status, { color: LampColor; hollow: boolean }> = {
  queued: { color: 'active', hollow: true },
  downloading: { color: 'active', hollow: false },
  paused: { color: 'idle', hollow: false },
  canceled: { color: 'idle', hollow: true },
  completed: { color: 'done', hollow: false },
  failed: { color: 'failed', hollow: false },
}

// - A task status: its lamp followed by `text`. A downloading task's lamp breathes.
export function StatusLamp({ status, text }: { status: Status; text: string }) {
  const lamp = STATUS_LAMP[status]
  return (
    <span className={styles.status}>
      <Lamp color={lamp.color} hollow={lamp.hollow} pulse={status === 'downloading'} />
      <span>{text}</span>
    </span>
  )
}
