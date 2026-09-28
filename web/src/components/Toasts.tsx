export interface Toast {
  id: number
  text: string
  kind: 'info' | 'error'
}

// - Stack of short-lived notices; errors are announced assertively to screen readers.
export default function Toasts({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`} role={t.kind === 'error' ? 'alert' : 'status'}>
          {t.text}
        </div>
      ))}
    </div>
  )
}
