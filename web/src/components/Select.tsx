import { Icon } from './icons'
import styles from './Select.module.css'

// - One choice out of a list that can grow, as the browser's own select in a recessed slot,
//   so the keyboard, type-ahead and the phone's native picker all work unchanged.
// - A drawn chevron sits over the slot's right end and ignores the pointer, so a click on it
//   still opens the list.
// - `lang` on an option marks its label's language, so each name is read in its own voice.

export interface SelectOption<T extends string> {
  value: T
  label: string
  lang?: string
}

interface Props<T extends string> {
  value: T
  options: SelectOption<T>[]
  onChange: (value: T) => void
  id?: string
  labelledBy?: string
  describedBy?: string
}

export function Select<T extends string>({ value, options, onChange, id, labelledBy, describedBy }: Props<T>) {
  const chosen = options.find((option) => option.value === value)
  return (
    <span className={styles.slot}>
      <select id={id} className={styles.select} value={value} lang={chosen?.lang}
        aria-labelledby={labelledBy} aria-describedby={describedBy}
        onChange={(event) => onChange(event.target.value as T)}>
        {options.map((option) => (
          <option key={option.value} value={option.value} lang={option.lang}>{option.label}</option>
        ))}
      </select>
      <span className={styles.chevron}><Icon name="chevron" /></span>
    </span>
  )
}
