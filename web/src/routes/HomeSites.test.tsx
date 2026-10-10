import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import providers from '../../../shared/providers.json'
import { api } from '../api/client'
import type { Resolved } from '../api/types'
import i18n from '../i18n'
import { Home } from './Home'

// - Renders the download page over a faked API and checks what an empty page shows: the row of
//   supported sites, and the hints that only make sense with a mouse and keyboard, in the
//   single and the batch preview.
// - `touch` installs a matchMedia whose touch-screen query matches; jsdom has none of its own.

const FREE = 100 * 2 ** 30
const LINK = 'https://k2s.cc/file/aaa111/a.rar'
const HINT = 'Paste a link anywhere on this page, or drop one here.'

const resolved: Resolved = {
  provider: 'k2s', file_id: 'aaa111', file_name: 'a.rar', size: 2 ** 30, resumable: true,
  duplicate: null, free_bytes: FREE, required_bytes: 2 * 2 ** 30,
}

function touch() {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn((query: string) => ({
      matches: query === '(hover: none) and (pointer: coarse)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
}

async function setup() {
  vi.spyOn(api, 'providers').mockResolvedValue(providers)
  vi.spyOn(api, 'tasks').mockResolvedValue([])
  vi.spyOn(api, 'storage').mockResolvedValue({ free_bytes: FREE, total_bytes: 4 * FREE })
  vi.spyOn(api, 'resolve').mockResolvedValue(resolved)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { user: userEvent.setup() }
}

async function pasteBatch(user: ReturnType<typeof userEvent.setup>) {
  vi.mocked(api.resolve).mockImplementation(async (url) => {
    const id = url.split('/')[4]
    return { ...resolved, file_id: id, file_name: `${id}.rar` }
  })
  await screen.findByRole('list', { name: 'Supported sites' })
  await user.click(screen.getByRole('textbox'))
  await user.paste('https://k2s.cc/file/bbb111/b.rar https://k2s.cc/file/ccc222/c.rar')
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

afterEach(() => {
  vi.restoreAllMocks()
  Reflect.deleteProperty(window, 'matchMedia')
})

describe('Home supported sites', () => {
  it('lists every supported site under an empty slot', async () => {
    await setup()
    const sites = await screen.findByRole('list', { name: 'Supported sites' })
    expect(within(sites).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['Keep2Share', 'MEGA', 'Google Drive'])
  })

  it('names the list in Chinese', async () => {
    await i18n.changeLanguage('zh-Hant-TW')
    await setup()
    expect(await screen.findByRole('list', { name: '支援的網站' })).toBeTruthy()
  })

  it('hides the list once a link is in the slot', async () => {
    const { user } = await setup()
    await screen.findByRole('list', { name: 'Supported sites' })
    await user.click(screen.getByRole('textbox'))
    await user.paste(LINK)
    await screen.findByRole('region', { name: 'a.rar' })
    expect(screen.queryByRole('list', { name: 'Supported sites' })).toBeNull()
  })
})

describe('Home hints by input device', () => {
  it('shows the paste hint and the key hint with a mouse and keyboard', async () => {
    const { user } = await setup()
    expect(await screen.findByText(HINT)).toBeTruthy()
    await user.click(screen.getByRole('textbox'))
    await user.paste(LINK)
    const preview = await screen.findByRole('region', { name: 'a.rar' })
    expect(preview.querySelector('kbd')).not.toBeNull()
  })

  it('leaves out the paste hint and the key hint on a touch screen', async () => {
    touch()
    const { user } = await setup()
    await screen.findByRole('list', { name: 'Supported sites' })
    expect(screen.queryByText(HINT)).toBeNull()
    await user.click(screen.getByRole('textbox'))
    await user.paste(LINK)
    const preview = await screen.findByRole('region', { name: 'a.rar' })
    expect(preview.querySelector('kbd')).toBeNull()
    expect(within(preview).getByRole('button', { name: 'Download' })).toBeTruthy()
  })

  it('shows the key hint on a batch with a mouse and keyboard', async () => {
    const { user } = await setup()
    await pasteBatch(user)
    const card = await screen.findByRole('region', { name: 'Batch of 2 links' })
    await within(card).findByRole('button', { name: 'Download 2 files' })
    expect(card.querySelector('kbd')).not.toBeNull()
  })

  it('leaves out the key hint on a batch on a touch screen', async () => {
    touch()
    const { user } = await setup()
    await pasteBatch(user)
    const card = await screen.findByRole('region', { name: 'Batch of 2 links' })
    await within(card).findByRole('button', { name: 'Download 2 files' })
    expect(card.querySelector('kbd')).toBeNull()
  })
})
