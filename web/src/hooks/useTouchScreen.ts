import { useSyncExternalStore } from 'react'

// - Whether the main input is a touch screen: no hover and a coarse pointer. Hints about
//   dragging, pasting anywhere on the page and keyboard keys are left out there.
// - Follows the media query live, so attaching a mouse or keyboard to a tablet brings the
//   hints back. False where matchMedia is missing, as in jsdom and on the server.

const QUERY = '(hover: none) and (pointer: coarse)'

function media(): MediaQueryList | null {
  return typeof window.matchMedia === 'function' ? window.matchMedia(QUERY) : null
}

function subscribe(onChange: () => void): () => void {
  const list = media()
  list?.addEventListener('change', onChange)
  return () => list?.removeEventListener('change', onChange)
}

export function useTouchScreen(): boolean {
  return useSyncExternalStore(subscribe, () => media()?.matches ?? false, () => false)
}
