import { afterEach, describe, expect, it, vi } from 'vitest'
import { prefersReducedMotion, withViewTransition } from './motion'

// - jsdom has neither the View Transitions API nor matchMedia, so each test installs the parts
//   it needs on the document and window, and removes them afterwards.

function install(target: object, name: string, value: unknown) {
  Object.defineProperty(target, name, { value, configurable: true, writable: true })
}

function reducedMotion(matches: boolean) {
  install(window, 'matchMedia', vi.fn(() => ({ matches })))
}

afterEach(() => {
  Reflect.deleteProperty(document, 'startViewTransition')
  Reflect.deleteProperty(window, 'matchMedia')
})

describe('withViewTransition', () => {
  it('runs the update at once without the View Transitions API', () => {
    const update = vi.fn()
    withViewTransition(update)
    expect(update).toHaveBeenCalledTimes(1)
  })

  it('runs the update inside a view transition when one is available', () => {
    const order: string[] = []
    const start = vi.fn((callback: () => void) => {
      order.push('start')
      callback()
    })
    install(document, 'startViewTransition', start)
    reducedMotion(false)
    withViewTransition(() => order.push('update'))
    expect(start).toHaveBeenCalledTimes(1)
    expect(order).toEqual(['start', 'update'])
  })

  it('skips the transition when reduced motion is set', () => {
    const start = vi.fn()
    install(document, 'startViewTransition', start)
    reducedMotion(true)
    const update = vi.fn()
    withViewTransition(update)
    expect(start).not.toHaveBeenCalled()
    expect(update).toHaveBeenCalledTimes(1)
  })
})

describe('prefersReducedMotion', () => {
  it('is false without matchMedia', () => {
    expect(prefersReducedMotion()).toBe(false)
  })

  it('follows the media query', () => {
    reducedMotion(true)
    expect(prefersReducedMotion()).toBe(true)
  })
})
