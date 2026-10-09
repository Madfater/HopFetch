import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import providers from '../../../shared/providers.json'
import { api } from '../api/client'
import type { Status, Task } from '../api/types'
import { LAST_VISIT_STORAGE_KEY } from '../hooks/useLastVisit'
import i18n from '../i18n'
import { Home } from './Home'

// - Renders the download page over a faked API with the tasks given.
// - A task's `completed_at` is its index plus 10, so the last-visit mark can split them.

function task(id: string, status: Status, change: Partial<Task> = {}): Task {
  return {
    id, provider: 'k2s', file_id: id, file_name: `${id}.rar`, size: 100, bytes_done: 0, speed: 0, eta: null,
    status, phase: null, message_key: null, message_params: {}, message: '', resumable: true, notice_key: null,
    file_exists: false, error: null, verified: null, created_at: 1, updated_at: 1, completed_at: null, ...change,
  }
}

function tasksOf(statuses: Status[]): Task[] {
  return statuses.map((status, i) => task(`t${i}`, status, { completed_at: status === 'completed' ? i + 10 : null }))
}

function setup(tasks: Task[]) {
  vi.spyOn(api, 'providers').mockResolvedValue(providers)
  vi.spyOn(api, 'tasks').mockResolvedValue(tasks)
  vi.spyOn(api, 'storage').mockResolvedValue({ free_bytes: 2 ** 40, total_bytes: 4 * 2 ** 40 })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const summary = () => screen.findByRole('list', { name: 'Task summary' })

beforeEach(async () => {
  localStorage.clear()
  await i18n.changeLanguage('en')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Home summary line', () => {
  it('counts each part and links it to its filter', async () => {
    localStorage.setItem(LAST_VISIT_STORAGE_KEY, '10')
    setup(tasksOf(['completed', 'completed', 'completed', 'failed', 'downloading', 'queued', 'paused']))
    const links = within(await summary()).getAllByRole('link')
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['2 finished', '/tasks?filter=completed'],
      ['1 needs you', '/tasks?filter=failed'],
      ['2 in progress', '/tasks?filter=active'],
      ['1 paused', '/tasks?filter=active'],
    ])
  })

  it('counts nothing as finished on a first visit and is absent when nothing else is left', async () => {
    setup(tasksOf(['completed', 'canceled']))
    await screen.findByRole('heading', { name: 'Recent tasks' })
    expect(screen.queryByRole('list', { name: 'Task summary' })).not.toBeInTheDocument()
  })

  it('stores the newest completion as the mark when the page closes', async () => {
    localStorage.setItem(LAST_VISIT_STORAGE_KEY, '5')
    const { unmount } = setup(tasksOf(['canceled', 'completed', 'completed']))
    expect(within(await summary()).getByRole('link')).toHaveTextContent('2 finished')
    unmount()
    expect(localStorage.getItem(LAST_VISIT_STORAGE_KEY)).toBe('12')
  })

  it('has no underlined red attention line', async () => {
    setup(tasksOf(['failed']))
    await summary()
    expect(screen.queryByText(/need attention|needs attention/)).not.toBeInTheDocument()
  })
})

describe('Home recent tasks', () => {
  it('are links to their row, with progress for paused and downloading tasks', async () => {
    setup([
      task('a', 'paused', { bytes_done: 40 }),
      task('b', 'downloading', { size: null, bytes_done: 3 * 2 ** 20 }),
      task('c', 'paused', { size: null }),
    ])
    const recent = await screen.findByRole('region', { name: 'Recent tasks' })
    const links = within(recent).getAllByRole('link').filter((link) => link.getAttribute('href')?.includes('focus'))
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['/tasks?focus=a', '/tasks?focus=b', '/tasks?focus=c'])
    expect(links[0]).toHaveTextContent('40%')
    expect(links[1]).toHaveTextContent('3.00 MB')
    expect(links[2]).toHaveTextContent(/^c\.rarPaused$/)
  })
})

describe('Home slot description', () => {
  it('names the lamp state, and the hint only while it shows', async () => {
    setup([])
    const input = screen.getByRole('textbox')
    expect(input).toHaveAttribute('aria-describedby', 'link-lamp link-status link-hint')
    expect(document.getElementById('link-lamp')).toHaveTextContent('Waiting for a link')
    expect(document.getElementById('link-hint')).toBeInTheDocument()

    await userEvent.setup().type(input, 'x')
    expect(document.getElementById('link-hint')).not.toBeInTheDocument()
    expect(input).toHaveAttribute('aria-describedby', 'link-lamp link-status')
  })

  it('keeps the supported sites row in place while typing', async () => {
    setup([])
    const sites = await screen.findByRole('list', { name: 'Supported sites' })
    await userEvent.setup().type(screen.getByRole('textbox'), 'x')
    expect(sites).toBeInTheDocument()
    expect(sites.className).toMatch(/sitesHidden/)
  })
})
