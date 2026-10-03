import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'
import i18n from '../i18n'
import { useToast } from './toast-context'
import { ToastProvider } from './Toasts'

// - A button that pushes numbered notices, inside the provider.

function Pusher() {
  const toast = useToast()
  const count = useRef(0)
  return (
    <button type="button" onClick={() => toast(`Notice ${++count.current}`)}>
      Push
    </button>
  )
}

function shown() {
  return screen.queryAllByText(/^Notice \d+$/).map((node) => node.textContent)
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('ToastProvider', () => {
  it('shows at most four notices, dropping the oldest', async () => {
    const user = userEvent.setup()
    render(<ToastProvider><Pusher /></ToastProvider>)
    for (let i = 0; i < 5; i++) await user.click(screen.getByRole('button', { name: 'Push' }))
    expect(shown()).toEqual(['Notice 2', 'Notice 3', 'Notice 4', 'Notice 5'])
  })

  it('does not count a notice that is sliding out', async () => {
    const user = userEvent.setup()
    render(<ToastProvider><Pusher /></ToastProvider>)
    for (let i = 0; i < 4; i++) await user.click(screen.getByRole('button', { name: 'Push' }))
    const close = screen.getAllByRole('button', { name: 'Close notification' })
    await user.click(close[close.length - 1])
    await user.click(screen.getByRole('button', { name: 'Push' }))
    expect(shown()).toEqual(expect.arrayContaining(['Notice 1', 'Notice 2', 'Notice 3', 'Notice 5']))
  })
})
