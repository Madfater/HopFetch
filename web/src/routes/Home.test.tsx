import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import providers from '../../../shared/providers.json'
import { api } from '../api/client'
import type { Resolved, Task } from '../api/types'
import i18n from '../i18n'
import controls from '../styles/controls.module.css'
import { Home } from './Home'

// - Renders the download page over a faked API: the shared provider list, no tasks, the storage
//   below, and a resolve that answers with the given file.
// - A link is pasted into the input, which resolves it at once.

const LINK = 'https://k2s.cc/file/aaa111/a.rar'
const FREE = 100 * 2 ** 30

function resolved(change: Partial<Resolved> = {}): Resolved {
  return {
    provider: 'k2s', file_id: 'aaa111', file_name: 'a.rar', size: 2 ** 30, resumable: true,
    duplicate: null, free_bytes: FREE, required_bytes: 2 * 2 ** 30, ...change,
  }
}

function task(id: string): Task {
  return {
    id, provider: 'k2s', file_id: 'aaa111', file_name: 'a.rar', size: 2 ** 30, bytes_done: 0, speed: 0, eta: null,
    status: 'queued', phase: null, message_key: null, message_params: {}, message: '', resumable: true,
    notice_key: null, file_exists: false, error: null, verified: null, created_at: 1, updated_at: 1,
    completed_at: null,
  }
}

async function setup(answer: Resolved) {
  vi.spyOn(api, 'providers').mockResolvedValue(providers)
  vi.spyOn(api, 'tasks').mockResolvedValue([])
  vi.spyOn(api, 'storage').mockResolvedValue({ free_bytes: FREE, total_bytes: 4 * FREE })
  vi.spyOn(api, 'resolve').mockResolvedValue(answer)
  const create = vi.spyOn(api, 'create').mockResolvedValue(task('task1'))
  const retry = vi.spyOn(api, 'retry').mockResolvedValue(task('old1'))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  const user = userEvent.setup()
  await vi.waitFor(() => expect(api.providers).toHaveBeenCalled())
  await user.click(screen.getByRole('textbox'))
  await user.paste(LINK)
  await screen.findByRole('region', { name: 'a.rar' })
  return { create, retry, user }
}

const keyHint = () => screen.getByRole('region', { name: 'a.rar' }).querySelector('kbd')?.parentElement?.textContent

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Home preview keys', () => {
  it('starts a plain download on Enter and says so', async () => {
    const { create, user } = await setup(resolved())
    expect(keyHint()).toBe('Enter to download, Esc to clear')
    await user.keyboard('{Enter}')
    expect(create).toHaveBeenCalledWith(LINK, false)
  })

  it('needs a click to download a completed file again', async () => {
    const { create, user } = await setup(resolved({ duplicate: { task_id: 'old1', status: 'completed' } }))
    expect(keyHint()).toBe('Esc to clear')
    await user.keyboard('{Enter}')
    expect(create).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Download again' }))
    expect(create).toHaveBeenCalledWith(LINK, true)
  })

  it('needs a click to retry a failed earlier task', async () => {
    const { retry, user } = await setup(resolved({ duplicate: { task_id: 'old1', status: 'failed' } }))
    expect(keyHint()).toBe('Esc to clear')
    await user.keyboard('{Enter}')
    expect(retry).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(retry).toHaveBeenCalledWith('old1')
  })

  it('makes retry the primary action over view task', async () => {
    await setup(resolved({ duplicate: { task_id: 'old1', status: 'failed' } }))
    expect(screen.getByRole('button', { name: 'Retry' }).className).toContain(controls.primary)
    expect(screen.getByRole('link', { name: 'View task' }).className).not.toContain(controls.primary)
  })

  it('names Esc alone in Traditional Chinese when Enter does not download', async () => {
    await i18n.changeLanguage('zh-Hant-TW')
    await setup(resolved({ duplicate: { task_id: 'old1', status: 'completed' } }))
    expect(keyHint()).toBe('按 Esc 清除')
  })

  it('offers no retry while the file does not fit', async () => {
    const { retry, user } = await setup(resolved({
      duplicate: { task_id: 'old1', status: 'canceled' }, required_bytes: 2 * FREE,
    }))
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    expect(screen.getByRole('link', { name: 'View task' })).toBeTruthy()
    await user.keyboard('{Enter}')
    expect(retry).not.toHaveBeenCalled()
  })
})

describe('Home slot lamp', () => {
  it('keeps showing the link state while a link is dragged over the slot', async () => {
    await setup(resolved())
    expect(screen.getByText('Ready to download')).toBeTruthy()
    const slot = screen.getByRole('textbox').parentElement as HTMLElement
    fireEvent.dragEnter(slot, { dataTransfer: { types: ['text/uri-list'] } })
    expect(screen.getByRole('textbox').getAttribute('placeholder')).toBe('Drop to check this link')
    expect(screen.getByText('Ready to download')).toBeTruthy()
    expect(screen.queryByText('Checking')).toBeNull()
  })
})

describe('Home typed input', () => {
  it('waits for the typing to stop before calling a link invalid', async () => {
    vi.spyOn(api, 'providers').mockResolvedValue(providers)
    vi.spyOn(api, 'tasks').mockResolvedValue([])
    vi.spyOn(api, 'storage').mockResolvedValue({ free_bytes: FREE, total_bytes: 4 * FREE })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Home />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const user = userEvent.setup()
    await vi.waitFor(() => expect(api.providers).toHaveBeenCalled())
    const input = screen.getByRole('textbox')
    await user.type(input, 'h')
    expect(screen.queryByText(/not a valid URL/)).not.toBeInTheDocument()
    expect(input).not.toHaveAttribute('aria-invalid')

    fireEvent.blur(input)
    expect(await screen.findByText(/not a valid URL/)).toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'true')
  })
})
