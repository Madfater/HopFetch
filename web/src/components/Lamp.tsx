import type { Status } from '../api/types'
import styles from './Lamp.module.css'

// - An indicator light. Color is never the only signal: callers always put text beside it.

export type LampColor = 'off' | 'amber' | 'green' | 'red' | 'steel'

export function Lamp({ color, hollow = false }: { color: LampColor; hollow?: boolean }) {
  return <span aria-hidden="true" className={`${styles.lamp} ${styles[color]} ${hollow ? styles.hollow : ''}`} />
}

const STATUS_LAMP: Record<Status, { color: LampColor; hollow: boolean }> = {
  queued: { color: 'amber', hollow: true },
  downloading: { color: 'amber', hollow: false },
  paused: { color: 'steel', hollow: false },
  canceled: { color: 'steel', hollow: true },
  completed: { color: 'green', hollow: false },
  failed: { color: 'red', hollow: false },
}

// - A task status: its lamp followed by `text`.
export function StatusLamp({ status, text }: { status: Status; text: string }) {
  const lamp = STATUS_LAMP[status]
  return (
    <span className={styles.status}>
      <Lamp color={lamp.color} hollow={lamp.hollow} />
      <span>{text}</span>
    </span>
  )
}
