import { Icon } from './icons'
import styles from './NumberStepper.module.css'

// - A number field between a minus and a plus button, in one recessed slot, with an optional
//   unit after the value.
// - The field is a native number input with its spinners hidden, so arrow keys still step it.
//   The buttons stay out of the tab order, since the arrow keys do the same, and are disabled
//   at the limits the caller reports.

interface Props {
  id: string
  value: string
  min: number
  max?: number
  unit?: string
  atMin: boolean
  atMax: boolean
  invalid: boolean
  describedBy: string
  decreaseLabel: string
  increaseLabel: string
  onChange: (value: string) => void
  onStep: (delta: number) => void
  onBlur: () => void
}

export function NumberStepper(props: Props) {
  const { id, value, min, max, unit, atMin, atMax, invalid, describedBy, onChange, onStep, onBlur } = props
  return (
    <div className={`${styles.stepper} ${invalid ? styles.invalid : ''}`}>
      <button type="button" className={styles.step} tabIndex={-1} aria-label={props.decreaseLabel} disabled={atMin}
        onClick={() => onStep(-1)}>
        <Icon name="minus" />
      </button>
      <input id={id} className={`${styles.input} num`} type="number" inputMode="numeric" min={min} max={max} step={1}
        value={value} aria-invalid={invalid || undefined} aria-describedby={describedBy}
        onChange={(event) => onChange(event.target.value)} onBlur={onBlur} />
      {unit && <span className={styles.unit} aria-hidden="true">{unit}</span>}
      <button type="button" className={styles.step} tabIndex={-1} aria-label={props.increaseLabel} disabled={atMax}
        onClick={() => onStep(1)}>
        <Icon name="plus" />
      </button>
    </div>
  )
}
