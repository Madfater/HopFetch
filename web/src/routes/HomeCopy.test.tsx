import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import providers from '../../../shared/providers.json'
import { api } from '../api/client'
import type { Resolved } from '../api/types'
import i18n from '../i18n'
import { Home } from './Home'

// - Renders the download page over a faked API and checks the text that tells the user what
//   the page takes and what happens after a download starts.

const FREE = 100 * 2 ** 30
const PROMISE = 'Saves to the NAS download folder. You can close this page; the download continues on the server.'

function file(change: Partial<Resolved> = {}): Resolved {
  return {
    provider: 'k2s', file_id: 'aaa111', file_name: 'a.rar', size: 2 ** 30, resumable: true,
    duplicate: null, free_bytes: FREE, required_bytes: 2 * 2 ** 30, ...change,
  }
}

function setup(answer: Resolved = file()) {
  vi.spyOn(api, 'providers').mockResolvedValue(providers)
  vi.spyOn(api, 'tasks').mockResolvedValue([])
  vi.spyOn(api, 'storage').mockResolvedValue({ free_bytes: FREE, total_bytes: 4 * FREE })
  vi.spyOn(api, 'resolve').mockResolvedValue(answer)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Home copy', () => {
  it('names the supported sites in the empty input', async () => {
    setup()
    await vi.waitFor(() =>
      expect(screen.getByRole('textbox')).toHaveAttribute('placeholder', 'Paste a Keep2Share or MEGA link'),
    )
  })

  it('names the supported sites when a link is from another site', async () => {
    const user = setup()
    await vi.waitFor(() => expect(api.providers).toHaveBeenCalled())
    await user.click(screen.getByRole('textbox'))
    await user.paste('https://example.com/file/abc')
    await screen.findByText('Only Keep2Share and MEGA links are supported.')
  })

  it('says where a downloadable file goes and that the page can be closed', async () => {
    const user = setup()
    await vi.waitFor(() => expect(api.providers).toHaveBeenCalled())
    await user.click(screen.getByRole('textbox'))
    await user.paste('https://k2s.cc/file/aaa111/a.rar')
    await screen.findByRole('region', { name: 'a.rar' })
    expect(screen.getByText(PROMISE)).toBeTruthy()
  })

  it('leaves the promise out when the file cannot be downloaded', async () => {
    const user = setup(file({ required_bytes: 2 * FREE }))
    await vi.waitFor(() => expect(api.providers).toHaveBeenCalled())
    await user.click(screen.getByRole('textbox'))
    await user.paste('https://k2s.cc/file/aaa111/a.rar')
    await screen.findByRole('region', { name: 'a.rar' })
    expect(screen.queryByText(PROMISE)).toBeNull()
  })

  it('says the promise in Traditional Chinese', async () => {
    await i18n.changeLanguage('zh-Hant-TW')
    const user = setup()
    await vi.waitFor(() => expect(api.providers).toHaveBeenCalled())
    await user.click(screen.getByRole('textbox'))
    await user.paste('https://k2s.cc/file/aaa111/a.rar')
    await screen.findByText('完成後會存到 NAS 的下載資料夾。可以關閉這頁，下載會在伺服器上繼續。')
  })
})
