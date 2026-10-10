import { useCallback, useState } from 'react'

// - Whether new downloads go through proxies, remembered per browser; on until turned off.
// - Where storage is blocked the choice starts on and lasts until the page reloads.

export const PROXY_CHOICE_STORAGE_KEY = 'use-proxy'

function read(): boolean {
  try {
    return localStorage.getItem(PROXY_CHOICE_STORAGE_KEY) !== 'off'
  } catch {
    return true
  }
}

export function useProxyChoice(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(read)
  const change = useCallback((next: boolean) => {
    setOn(next)
    try {
      localStorage.setItem(PROXY_CHOICE_STORAGE_KEY, next ? 'on' : 'off')
    } catch {
      // - Storage may be blocked; the choice then lasts until the page reloads.
    }
  }, [])
  return [on, change]
}
