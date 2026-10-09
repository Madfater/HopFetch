import { Checkbox, Dialog } from 'radix-ui'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatBytes } from '../lib/format'
import controls from '../styles/controls.module.css'
import styles from './ConfirmDialog.module.css'

// - Confirms canceling or deleting a task. Both are offered from the files page and both are
//   asked first, because both throw away the part files of an unfinished task.
// - `discards` is the number of downloaded bytes the action deletes; when it is above zero the
//   dialog states it in red, so the cost is read before the red button.
// - "Also delete the file on the NAS" starts unchecked and is only offered for deleting a
//   completed task, the only kind with a file on the NAS.
// - The dialog is opened by state rather than by a Radix trigger, so it remembers the element
//   that had focus when it opened and gives focus back to it on close, while that element is
//   still on the page.
// - It opens with focus on Keep, the safe choice, so Enter or Space never confirms or ticks the
//   file option by accident.

export type ConfirmKind = 'cancel' | 'delete'

interface Props {
  kind: ConfirmKind
  name: string
  discards: number
  canDeleteFile: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (deleteFile: boolean) => void
}

export function ConfirmDialog({ kind, name, discards, canDeleteFile, open, onOpenChange, onConfirm }: Props) {
  const { t, i18n } = useTranslation()
  const [deleteFile, setDeleteFile] = useState(false)
  const returnFocus = useRef<HTMLElement | null>(null)
  const keep = useRef<HTMLButtonElement>(null)

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) setDeleteFile(false)
        onOpenChange(next)
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.content}
          onOpenAutoFocus={(event) => {
            returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
            event.preventDefault()
            keep.current?.focus()
          }}
          onCloseAutoFocus={(event) => {
            if (!returnFocus.current?.isConnected) return
            event.preventDefault()
            returnFocus.current.focus()
          }}
        >
          <Dialog.Title className={styles.title}>{t(`confirmDialog.${kind}.title`)}</Dialog.Title>
          <Dialog.Description asChild>
            <div className={styles.body}>
              <p>{t(`confirmDialog.${kind}.body`, { name })}</p>
              {discards > 0 && (
                <p className={styles.cost}>{t('confirmDialog.discards', { size: formatBytes(i18n.language, discards) })}</p>
              )}
            </div>
          </Dialog.Description>
          {kind === 'delete' && canDeleteFile && (
            <label className={styles.check}>
              <Checkbox.Root className={styles.box} checked={deleteFile}
                onCheckedChange={(value) => setDeleteFile(value === true)}>
                <Checkbox.Indicator>
                  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor"
                    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path className={styles.mark} pathLength={1} d="M2.5 6.2 5 8.5l4.5-5" />
                  </svg>
                </Checkbox.Indicator>
              </Checkbox.Root>
              {t('confirmDialog.deleteFile')}
            </label>
          )}
          <div className={styles.actions}>
            <Dialog.Close asChild>
              <button ref={keep} type="button" className={controls.button}>
                {t('confirmDialog.keep')}
              </button>
            </Dialog.Close>
            <button
              type="button"
              className={`${controls.button} ${controls.danger}`}
              onClick={() => {
                onConfirm(kind === 'delete' && canDeleteFile && deleteFile)
                setDeleteFile(false)
              }}
            >
              {t(`confirmDialog.${kind}.confirm`)}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
