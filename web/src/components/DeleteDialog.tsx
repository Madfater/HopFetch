import { Checkbox, Dialog } from 'radix-ui'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import controls from '../styles/controls.module.css'
import styles from './DeleteDialog.module.css'

// - Confirms deleting a task. "Also delete the file on the NAS" starts unchecked and is only
//   offered for completed tasks, the only ones with a file on the NAS.
// - The dialog is opened by state rather than by a Radix trigger, so it remembers the element
//   that had focus when it opened and gives focus back to it on close, while that element is
//   still on the page.

interface Props {
  name: string
  canDeleteFile: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (deleteFile: boolean) => void
}

export function DeleteDialog({ name, canDeleteFile, open, onOpenChange, onConfirm }: Props) {
  const { t } = useTranslation()
  const [deleteFile, setDeleteFile] = useState(false)
  const returnFocus = useRef<HTMLElement | null>(null)

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
          onOpenAutoFocus={() => {
            returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
          }}
          onCloseAutoFocus={(event) => {
            if (!returnFocus.current?.isConnected) return
            event.preventDefault()
            returnFocus.current.focus()
          }}
        >
          <Dialog.Title className={styles.title}>{t('deleteDialog.title')}</Dialog.Title>
          <Dialog.Description className={styles.body}>{t('deleteDialog.body', { name })}</Dialog.Description>
          {canDeleteFile && (
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
              {t('deleteDialog.deleteFile')}
            </label>
          )}
          <div className={styles.actions}>
            <Dialog.Close asChild>
              <button type="button" className={controls.button}>
                {t('deleteDialog.cancel')}
              </button>
            </Dialog.Close>
            <button
              type="button"
              className={`${controls.button} ${controls.danger}`}
              onClick={() => {
                onConfirm(deleteFile)
                setDeleteFile(false)
              }}
            >
              {t('deleteDialog.confirm')}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
