import { flushSync } from 'react-dom'

// - `prefersReducedMotion` reads the user's motion setting; it is false where matchMedia is
//   missing, as in tests.
// - `withViewTransition` runs a state update inside a view transition, so the browser animates
//   from the page before the update to the page after it. Elements with a
//   `view-transition-name` move on their own; the rest of the page crossfades.
// - Without the View Transitions API, or with reduced motion set, the update runs at once.

export function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function withViewTransition(update: () => void): void {
  if (typeof document.startViewTransition !== 'function' || prefersReducedMotion()) {
    update()
    return
  }
  document.startViewTransition(() => flushSync(update))
}
