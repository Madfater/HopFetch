import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../api/client'
import type { Settings as SettingsData } from '../api/types'
import i18n from '../i18n'
import { MIB } from '../lib/settings'
import { Settings } from './Settings'

// - Renders the settings page over a faked API: the saved settings below, a storage answer,
//   and a save that returns the saved settings with the change applied.

const SAVED: SettingsData = {
  connections: 20, split_size: 20 * MIB, use_proxies: true, max_active_jobs: 2, download_root: '/volume1/downloads',
}

function setup() {
  vi.spyOn(api, 'settings').mockResolvedValue(SAVED)
  vi.spyOn(api, 'storage').mockResolvedValue({ free_bytes: 2 ** 40, total_bytes: 4 * 2 ** 40 })
  const save = vi.spyOn(api, 'saveSettings').mockImplementation(async (change) => ({ ...SAVED, ...change }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Settings />
    </QueryClientProvider>,
  )
  return { save, user: userEvent.setup() }
}

const saveButton = () => screen.getByRole('button', { name: 'Save settings' })

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('Settings', () => {
  it('counts unsaved changes and enables Save only when there are some', async () => {
    const { user } = setup()
    const connections = await screen.findByLabelText('Connections per task')
    expect(saveButton()).toBeDisabled()
    expect(screen.getByText('Changes apply to tasks created after you save.')).toBeInTheDocument()

    await user.clear(connections)
    await user.type(connections, '32')
    await user.click(screen.getByRole('switch', { name: 'Use public proxies' }))
    expect(screen.getByText('2 unsaved changes')).toBeInTheDocument()
    expect(saveButton()).toBeEnabled()
  })

  it('restores the saved values on Discard', async () => {
    const { user } = setup()
    const connections = await screen.findByLabelText('Connections per task')
    await user.clear(connections)
    await user.type(connections, '48')
    await user.click(screen.getByRole('button', { name: 'Discard' }))
    expect(connections).toHaveValue(20)
    expect(screen.queryByRole('button', { name: 'Discard' })).not.toBeInTheDocument()
    expect(saveButton()).toBeDisabled()
  })

  it('shows a value out of range once the field loses focus', async () => {
    const { user } = setup()
    const active = await screen.findByLabelText('Simultaneous downloads')
    await user.clear(active)
    await user.type(active, '12')
    expect(screen.queryByText('Simultaneous downloads must be between 1 and 10.')).not.toBeInTheDocument()
    await user.tab()
    expect(screen.getByText('Simultaneous downloads must be between 1 and 10.')).toBeInTheDocument()
    expect(active).toHaveAttribute('aria-invalid', 'true')
  })

  it('sends nothing for an invalid draft and focuses the field in trouble', async () => {
    const { save, user } = setup()
    const connections = await screen.findByLabelText('Connections per task')
    await user.clear(connections)
    await user.type(connections, '0')
    await user.click(saveButton())
    expect(save).not.toHaveBeenCalled()
    expect(connections).toHaveFocus()
    expect(screen.getByText('Connections must be between 1 and 64.')).toBeInTheDocument()
  })

  it('saves only the changed settings, with the part size in bytes', async () => {
    const { save, user } = setup()
    await user.click(await screen.findByRole('button', { name: 'Increase: Part size' }))
    await user.click(screen.getByRole('switch', { name: 'Use public proxies' }))
    await user.click(saveButton())
    expect(save).toHaveBeenCalledTimes(1)
    expect(save.mock.calls[0][0]).toEqual({ split_size: 21 * MIB, use_proxies: false })
    expect(await screen.findByText('Settings saved')).toBeInTheDocument()
    expect(saveButton()).toBeDisabled()
  })

  it('keeps an edit made while a save runs, and runs one save at a time', async () => {
    const { save, user } = setup()
    let finish = () => {}
    save.mockImplementationOnce((change) => new Promise((resolve) => {
      finish = () => resolve({ ...SAVED, ...change })
    }))
    const connections = await screen.findByLabelText('Connections per task')
    await user.click(screen.getByRole('switch', { name: 'Use public proxies' }))
    await user.click(saveButton())
    await user.clear(connections)
    await user.type(connections, '30')
    await user.click(saveButton())
    expect(save).toHaveBeenCalledTimes(1)

    await act(async () => finish())
    expect(connections).toHaveValue(30)
    expect(screen.getByText('1 unsaved change')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Use public proxies' })).toHaveAttribute('aria-checked', 'false')
  })

  it('keeps showing a problem found while a save runs', async () => {
    const { save, user } = setup()
    let finish = () => {}
    save.mockImplementationOnce((change) => new Promise((resolve) => {
      finish = () => resolve({ ...SAVED, ...change })
    }))
    await user.click(await screen.findByRole('switch', { name: 'Use public proxies' }))
    await user.click(saveButton())
    const connections = screen.getByLabelText('Connections per task')
    await user.clear(connections)
    await user.type(connections, '0')
    await user.tab()
    await act(async () => finish())
    expect(screen.getByText('Connections must be between 1 and 64.')).toBeInTheDocument()
    expect(connections).toHaveAttribute('aria-invalid', 'true')
  })

  it('stops the stepper buttons at the limits', async () => {
    const { user } = setup()
    const decrease = await screen.findByRole('button', { name: 'Decrease: Part size' })
    expect(decrease).toBeDisabled()
    const active = screen.getByLabelText('Simultaneous downloads')
    await user.clear(active)
    await user.type(active, '10')
    expect(screen.getByRole('button', { name: 'Increase: Simultaneous downloads' })).toBeDisabled()
  })

  it('shows a refused save in the footer', async () => {
    const { save, user } = setup()
    save.mockRejectedValueOnce(
      new ApiError(400, { code: 'invalid_settings', key: 'errors.invalid_settings', params: {}, message: '' }),
    )
    await user.click(await screen.findByRole('switch', { name: 'Use public proxies' }))
    await user.click(saveButton())
    expect(await screen.findByRole('alert')).toHaveTextContent('A setting is out of range.')
  })

  it('shows the download folder and its free space', async () => {
    setup()
    expect(await screen.findByText('/volume1/downloads')).toBeInTheDocument()
    expect(await screen.findByText('1.00 TB free of 4.00 TB')).toBeInTheDocument()
  })

  it('applies the language at once', async () => {
    const { user } = setup()
    await user.click(await screen.findByRole('radio', { name: '繁體中文' }))
    expect(i18n.language).toBe('zh-Hant-TW')
    expect(await screen.findByRole('heading', { level: 1, name: '設定' })).toBeInTheDocument()
  })
})
