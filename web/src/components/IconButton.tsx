import { Tooltip } from 'radix-ui'
import styles from './IconButton.module.css'
import { Icon, type IconName } from './icons'

// - An icon-only action with an aria-label and a matching tooltip.
// - With `href`, it is a link that downloads the file instead of a button; a disabled link is
//   rendered as a disabled button so it cannot be followed.
// - A disabled button is marked `aria-disabled` rather than `disabled` and ignores clicks, so it
//   stays in the tab order, is announced as dimmed, and still shows its tooltip, which says why.

interface Props {
  icon: IconName
  label: string
  tooltip?: string
  onClick?: () => void
  href?: string
  disabled?: boolean
}

export function IconButton({ icon, label, tooltip, onClick, href, disabled = false }: Props) {
  const control =
    href && !disabled ? (
      <a className={styles.button} href={href} download aria-label={label}>
        <Icon name={icon} />
      </a>
    ) : (
      <button type="button" className={styles.button} aria-label={label}
        aria-disabled={disabled || undefined} onClick={disabled ? undefined : onClick}>
        <Icon name={icon} />
      </button>
    )
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{control}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className={styles.tooltip} sideOffset={4}>
          {tooltip ?? label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}
