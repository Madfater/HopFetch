import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from './icons'
import { Lamp } from './Lamp'
import { ToastContext, type ToastKind } from './toast-context'
import styles from './Toasts.module.css'

// - In-page notices. Errors stay until closed or for ERROR_MS; others for INFO_MS.
// - Errors are announced assertively, others politely.
// - Closing, by hand or by timer, first marks the notice as leaving, which plays its slide-out,
//   and removes it LEAVE_MS later. LEAVE_MS covers the slide-out's `--motion-fast` duration.

interface Toast {
  id: number
  text: string
  kind: ToastKind
  leaving: boolean
}

const INFO_MS = 5000
const ERROR_MS = 10000
const LEAVE_MS = 150

export function ToastProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const [toasts, setToasts] = useState<Toast[]>([])
  const next = useRef(1)

  const close = useCallback((id: number) => {
    setToasts((all) => all.map((toast) => (toast.id === id ? { ...toast, leaving: true } : toast)))
    window.setTimeout(() => setToasts((all) => all.filter((toast) => toast.id !== id)), LEAVE_MS)
  }, [])

  const push = useCallback(
    (text: string, kind: ToastKind = 'info') => {
      const id = next.current++
      setToasts((all) => [...all.slice(-3), { id, text, kind, leaving: false }])
      window.setTimeout(() => close(id), kind === 'error' ? ERROR_MS : INFO_MS)
    },
    [close],
  )

  const value = useMemo(() => push, [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={styles.region}>
        <div aria-live="polite" role="status" className={styles.list}>
          {toasts.filter((toast) => toast.kind !== 'error').map((toast) => (
            <ToastItem key={toast.id} toast={toast} onClose={close} closeLabel={t('toast.close')} />
          ))}
        </div>
        <div aria-live="assertive" role="alert" className={styles.list}>
          {toasts.filter((toast) => toast.kind === 'error').map((toast) => (
            <ToastItem key={toast.id} toast={toast} onClose={close} closeLabel={t('toast.close')} />
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  )
}

const LAMP = { info: 'steel', success: 'green', error: 'red' } as const

function ToastItem({ toast, onClose, closeLabel }: { toast: Toast; onClose: (id: number) => void; closeLabel: string }) {
  return (
    <div className={`${styles.toast} ${toast.leaving ? styles.leaving : ''}`}>
      <span className={styles.lamp}>
        <Lamp color={LAMP[toast.kind]} />
      </span>
      <span className={styles.text}>{toast.text}</span>
      <button type="button" className={styles.close} aria-label={closeLabel} onClick={() => onClose(toast.id)}>
        <Icon name="cancel" />
      </button>
    </div>
  )
}
