import { Tooltip } from 'radix-ui'
import styles from './IconButton.module.css'
import { Icon, type IconName } from './icons'

// - An icon-only action with an aria-label and a matching tooltip.
// - With `href`, it is a link that downloads the file instead of a button; a disabled link is
//   rendered as a disabled button so it cannot be followed.
// - The `danger` tone marks an action that throws work away: it turns red while pointed at.

interface Props {
  icon: IconName
  label: string
  tooltip?: string
  onClick?: () => void
  href?: string
  disabled?: boolean
  tone?: 'danger'
}

export function IconButton({ icon, label, tooltip, onClick, href, disabled = false, tone }: Props) {
  const className = tone === 'danger' ? `${styles.button} ${styles.danger}` : styles.button
  const control =
    href && !disabled ? (
      <a className={className} href={href} download aria-label={label}>
        <Icon name={icon} />
      </a>
    ) : (
      <button type="button" className={className} aria-label={label} onClick={onClick}
        disabled={disabled}>
        <Icon name={icon} />
      </button>
    )
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{disabled ? <span tabIndex={0}>{control}</span> : control}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className={styles.tooltip} sideOffset={4}>
          {tooltip ?? label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}
