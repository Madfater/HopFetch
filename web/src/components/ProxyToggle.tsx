import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { Switch } from './Switch'
import styles from './ProxyToggle.module.css'

// - The proxy choice for the downloads a preview starts: a muted label and a switch, pushed to
//   the far end of the preview's action row.
// - The label names the switch, and a hidden line says what off means.

interface Props {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}

export function ProxyToggle({ checked, onCheckedChange }: Props) {
  const { t } = useTranslation()
  const id = useId()
  return (
    <span className={styles.toggle}>
      <label htmlFor={id} className={styles.label}>{t('preview.useProxy')}</label>
      <Switch id={id} checked={checked} describedBy={`${id}-hint`} onCheckedChange={onCheckedChange} />
      <span id={`${id}-hint`} className="visually-hidden">{t('preview.useProxyHint')}</span>
    </span>
  )
}
