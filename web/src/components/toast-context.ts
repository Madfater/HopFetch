import { createContext, useContext } from 'react'

// - The `push(text, kind)` function of the nearest ToastProvider.

export type ToastKind = 'info' | 'success' | 'error'

export const ToastContext = createContext<(text: string, kind?: ToastKind) => void>(() => {})

export function useToast() {
  return useContext(ToastContext)
}
