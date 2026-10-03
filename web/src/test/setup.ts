import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// - Unmounts rendered trees between tests.
// - jsdom has no ResizeObserver, which Radix form controls and the segmented control use; a
//   stand-in that never reports keeps them working.

class ResizeObserverStandIn {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver ??= ResizeObserverStandIn as unknown as typeof ResizeObserver

afterEach(() => cleanup())
