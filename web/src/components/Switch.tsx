import { Switch as RadixSwitch } from 'radix-ui'
import styles from './Switch.module.css'

// - An on/off switch, named by a `<label htmlFor>` with the same id.
// - Off is a recessed track with a steel knob. On fills the track with ink and the dark knob
//   slides across with a slight overshoot; the knob stretches while it is pressed.

interface Props {
  id: string
  checked: boolean
  describedBy?: string
  onCheckedChange: (checked: boolean) => void
}

export function Switch({ id, checked, describedBy, onCheckedChange }: Props) {
  return (
    <RadixSwitch.Root id={id} className={styles.track} checked={checked} aria-describedby={describedBy}
      onCheckedChange={onCheckedChange}>
      <RadixSwitch.Thumb className={styles.thumb} />
    </RadixSwitch.Root>
  )
}
