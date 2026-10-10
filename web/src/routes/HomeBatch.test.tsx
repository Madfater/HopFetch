import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import providers from '../../../shared/providers.json'
import { ApiError, api } from '../api/client'
import type { Resolved, Task } from '../api/types'
import i18n from '../i18n'
import { Home } from './Home'

// - Renders the download page over a faked API and pastes text with several links.
// - Each link's file id picks its lookup answer from `answers`; an id without an answer is not
//   found. A file of SIZE needs twice its size, as when parts and files share a disk.

const FREE = 100 * 2 ** 30
const SIZE = 2 ** 30
const link = (id: string) => `https://k2s.cc/file/${id}/${id}.rar`

function file(id: string, change: Partial<Resolved> = {}): Resolved {
  return {
    provider: 'k2s', file_id: id, file_name: `${id}.rar`, size: SIZE, resumable: true,
    duplicate: null, free_bytes: FREE, required_bytes: 2 * SIZE, ...change,
  }
}

function task(id: string): Task {
  return {
    id, url: 'https://k2s.cc/file/aaa111', provider: 'k2s', file_id: id, file_name: `${id}.rar`, size: SIZE, bytes_done: 0, speed: 0, eta: null,
    status: 'queued', phase: null, message_key: null, message_params: {}, message: '', resumable: true, use_proxy: true,
    notice_key: null, file_exists: false, error: null, retryable: true, verified: null, created_at: 1, updated_at: 1,
    completed_at: null,
  }
}

const notFound = () => new ApiError(404, { code: 'not_found', key: 'errors.not_found', params: {}, message: 'File not found.' })

function fileId(url: string) {
  return url.split('/')[4]
}

function setup(answers: Record<string, Resolved>, failCreate: string[] = []) {
  vi.spyOn(api, 'providers').mockResolvedValue(providers)
  vi.spyOn(api, 'tasks').mockResolvedValue([])
  vi.spyOn(api, 'storage').mockResolvedValue({ free_bytes: FREE, total_bytes: 4 * FREE })
  const resolve = vi.spyOn(api, 'resolve').mockImplementation(async (url) => {
    const answer = answers[fileId(url)]
    if (!answer) throw notFound()
    return answer
  })
  const create = vi.spyOn(api, 'create').mockImplementation(async (url) => {
    if (failCreate.includes(fileId(url))) throw notFound()
    return task(fileId(url))
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { resolve, create, user: userEvent.setup() }
}

async function paste(user: ReturnType<typeof userEvent.setup>, text: string) {
  await vi.waitFor(() => expect(api.providers).toHaveBeenCalled())
  await user.click(screen.getByRole('textbox'))
  await user.paste(text)
}

const card = () => screen.getByRole('region', { name: /^Batch of/ })
const rows = () => within(card()).getAllByRole('listitem')
const rowText = (id: string) => rows().find((row) => row.textContent?.includes(`${id}.rar`))?.textContent

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Home batch paste', () => {
  it('lists the supported links in order and checks at most three at once', async () => {
    const ids = ['b1', 'b2', 'b3', 'b4', 'b5']
    const waiting: (() => void)[] = []
    let running = 0
    let most = 0
    const { user } = setup({})
    vi.spyOn(api, 'resolve').mockImplementation((url) => {
      running += 1
      most = Math.max(most, running)
      return new Promise<Resolved>((resolve) => {
        waiting.push(() => {
          running -= 1
          resolve(file(fileId(url)))
        })
      })
    })
    await paste(user, `${ids.map(link).join('\n')}\nhttps://img.example.com/cover.jpg`)
    await screen.findByRole('region', { name: 'Batch of 5 links' })
    expect(screen.getByRole('textbox')).toHaveAttribute('placeholder', '5 links pasted')
    expect(screen.getByText('1 other link is not from a supported site and was left out.')).toBeTruthy()
    await vi.waitFor(() => expect(waiting).toHaveLength(3))
    while (waiting.length > 0) {
      waiting.shift()?.()
      await vi.waitFor(() => expect(running).toBeLessThanOrEqual(3))
      await new Promise((resolve) => setTimeout(resolve, 0))
    }
    await screen.findByText('5 files can be downloaded')
    expect(most).toBe(3)
    expect(rows().map((row) => row.querySelector('p')?.textContent)).toEqual(ids.map((id) => `${id}.rar`))
  })

  it('skips files that cannot start and counts only the rest', async () => {
    const { user } = setup({
      ok1: file('ok1'),
      act: file('act', { duplicate: { task_id: 'old1', status: 'queued' } }),
      done: file('done', { duplicate: { task_id: 'old2', status: 'completed' } }),
      bad: file('bad', { duplicate: { task_id: 'old3', status: 'failed' } }),
      stop: file('stop', { duplicate: { task_id: 'old4', status: 'canceled' } }),
      nosize: file('nosize', { size: null, required_bytes: null }),
    })
    await paste(user, ['ok1', 'act', 'done', 'bad', 'stop', 'nosize', 'gone'].map(link).join(' '))
    await screen.findByText('1 file can be downloaded')
    expect(rowText('stop')).toContain('This file failed or was canceled before.')
    expect(rowText('nosize')).toContain('The host did not report the file size, which a split download needs.')
    expect(rowText('act')).toContain('This file is already in the download list.')
    expect(rowText('done')).toContain('This file was downloaded before.')
    expect(rowText('bad')).toContain('This file failed or was canceled before.')
    expect(rowText('gone')).toContain('This file was not found. It may have been deleted.')
    expect(within(card()).getByRole('button', { name: 'Download 1 file' })).toBeEnabled()
  })

  it('starts nothing when the files do not all fit', async () => {
    const big = { size: FREE / 2, required_bytes: FREE * 0.6 }
    const { create, user } = setup({ p1: file('p1', big), p2: file('p2', big) })
    await paste(user, `${link('p1')} ${link('p2')}`)
    await screen.findByText(/^Not enough space for all of them: /)
    expect(screen.getByText('Not enough space for these 2 files.')).toBeTruthy()
    const button = within(card()).getByRole('button', { name: 'Download 2 files' })
    expect(button).toBeDisabled()
    await user.keyboard('{Enter}')
    expect(create).not.toHaveBeenCalled()
  })

  it('starts the files one by one in paste order and keeps going after a failure', async () => {
    const { create, user } = setup({ c1: file('c1'), c2: file('c2'), c3: file('c3') }, ['c2'])
    await paste(user, ['c1', 'c2', 'c3'].map(link).join('\n'))
    await user.click(await within(card()).findByRole('button', { name: 'Download 3 files' }))
    await vi.waitFor(() => expect(create).toHaveBeenCalledTimes(3))
    expect(create.mock.calls.map((call) => call[0])).toEqual(['c1', 'c2', 'c3'].map(link))
    await vi.waitFor(() => expect(rowText('c3')).toContain('Started'))
    expect(rowText('c1')).toContain('Started')
    expect(rowText('c2')).toContain('This file was not found. It may have been deleted.')
    expect(within(card()).queryByRole('button', { name: /^Download/ })).toBeNull()
    expect(screen.getByText('Started 2, 1 could not start.')).toBeTruthy()
    expect(screen.queryByText('Paste a link anywhere on this page, or drop one here.')).toBeNull()
  })

  it('ignores a paste elsewhere on the page while the batch is starting', async () => {
    const { create, user } = setup({ g1: file('g1'), g2: file('g2'), h1: file('h1'), h2: file('h2') })
    const pending: (() => void)[] = []
    create.mockImplementation((url) => new Promise<Task>((resolve) => pending.push(() => resolve(task(fileId(url))))))
    await paste(user, `${link('g1')} ${link('g2')}`)
    await screen.findByText('2 files can be downloaded')
    await user.click(within(card()).getByRole('button', { name: 'Download 2 files' }))
    await vi.waitFor(() => expect(pending).toHaveLength(1))

    expect(document.activeElement?.tagName).toBe('BUTTON')
    await user.paste(`${link('h1')} ${link('h2')}`)
    expect(screen.getByRole('region', { name: 'Batch of 2 links' })).toBeTruthy()
    expect(rowText('g1')).toBeTruthy()
    expect(rowText('h1')).toBeUndefined()

    pending.shift()?.()
    await vi.waitFor(() => expect(pending).toHaveLength(1))
    pending.shift()?.()
    await vi.waitFor(() => expect(screen.queryByRole('region', { name: /^Batch of/ })).toBeNull())
    expect(create.mock.calls.map((call) => call[0])).toEqual([link('g1'), link('g2')])
  })

  it('clears the batch once every file started', async () => {
    const { create, user } = setup({ d1: file('d1'), d2: file('d2') })
    await paste(user, `${link('d1')} ${link('d2')}`)
    await screen.findByText('2 files can be downloaded')
    await user.click(within(card()).getByRole('button', { name: 'Download 2 files' }))
    await vi.waitFor(() => expect(screen.queryByRole('region', { name: /^Batch of/ })).toBeNull())
    expect(create).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('starts on Enter only when every link can start', async () => {
    const { create, user } = setup({ e1: file('e1'), e2: file('e2', { duplicate: { task_id: 'old1', status: 'completed' } }) })
    await paste(user, `${link('e1')} ${link('e2')}`)
    await screen.findByText('1 file can be downloaded')
    expect(within(card()).getByText((_, el) => el?.tagName === 'SPAN' && el.textContent === 'Esc to clear')).toBeTruthy()
    await user.keyboard('{Enter}')
    expect(create).not.toHaveBeenCalled()

    await user.keyboard('{Escape}')
    vi.spyOn(api, 'resolve').mockImplementation(async (url) => file(fileId(url)))
    await paste(user, `${link('e3')} ${link('e4')}`)
    await screen.findByText('2 files can be downloaded')
    expect(within(card()).getByText((_, el) => el?.tagName === 'SPAN' && el.textContent === 'Enter to download, Esc to clear')).toBeTruthy()
    await user.keyboard('{Enter}')
    await vi.waitFor(() => expect(create).toHaveBeenCalledTimes(2))
  })

  it('clears the batch on Esc', async () => {
    const { user } = setup({ f1: file('f1'), f2: file('f2') })
    await paste(user, `${link('f1')} ${link('f2')}`)
    await screen.findByRole('region', { name: 'Batch of 2 links' })
    await user.keyboard('{Escape}')
    await vi.waitFor(() => expect(screen.queryByRole('region', { name: /^Batch of/ })).toBeNull())
    expect(screen.getByRole('textbox')).not.toHaveAttribute('placeholder', '2 links pasted')
  })

  it('uses the single preview when only one link is supported', async () => {
    const { user } = setup({ s1: file('s1') })
    await paste(user, `cover https://img.example.com/a.jpg\n${link('s1')}\nthread https://forum.example.com/t/1`)
    await screen.findByRole('region', { name: 's1.rar' })
    expect(screen.getByRole('textbox')).toHaveValue(link('s1'))
    expect(screen.queryByRole('region', { name: /^Batch of/ })).toBeNull()
  })

  it('names the supported sites when no link is supported', async () => {
    const { user } = setup({})
    await paste(user, 'https://img.example.com/a.jpg https://forum.example.com/t/1')
    await screen.findByText('None of these links are from a supported site: Keep2Share, MEGA, MediaFire, and Dropbox.')
  })
})

describe('Home batch proxy choice', () => {
  beforeEach(() => localStorage.clear())

  it('starts every file of the batch with the proxy choice', async () => {
    const { create, user } = setup({ x1: file('x1'), x2: file('x2') })
    await paste(user, ['x1', 'x2'].map(link).join('\n'))
    const button = await within(card()).findByRole('button', { name: 'Download 2 files' })
    const proxy = within(card()).getByRole('switch', { name: 'Use proxy' })
    expect(proxy).toHaveAttribute('aria-checked', 'true')
    await user.click(proxy)
    await user.click(button)
    await vi.waitFor(() => expect(create).toHaveBeenCalledTimes(2))
    expect(create.mock.calls.map((call) => call[2])).toEqual([false, false])
  })
})
