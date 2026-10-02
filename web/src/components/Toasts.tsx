import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from './icons'
import { ToastContext, type ToastKind } from './toast-context'
import styles from './Toasts.module.css'

// - In-page notices. Errors stay until closed or for ERROR_MS; others for INFO_MS.
// - Errors are announced assertively, others politely.

interface Toast {
  id: number
  text: string
  kind: ToastKind
}

const INFO_MS = 5000
const ERROR_MS = 10000

export function ToastProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const [toasts, setToasts] = useState<Toast[]>([])
  const next = useRef(1)

  const close = useCallback((id: number) => setToasts((all) => all.filter((toast) => toast.id !== id)), [])

  const push = useCallback(
    (text: string, kind: ToastKind = 'info') => {
      const id = next.current++
      setToasts((all) => [...all.slice(-3), { id, text, kind }])
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

function ToastItem({ toast, onClose, closeLabel }: { toast: Toast; onClose: (id: number) => void; closeLabel: string }) {
  return (
    <div className={`${styles.toast} ${toast.kind === 'success' ? styles.success : ''} ${toast.kind === 'error' ? styles.error : ''}`}>
      <span className={styles.text}>{toast.text}</span>
      <button type="button" className={styles.close} aria-label={closeLabel} onClick={() => onClose(toast.id)}>
        <Icon name="cancel" />
      </button>
    </div>
  )
}
