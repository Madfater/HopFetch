import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { Status, Task } from '../api/types'
import i18n from '../i18n'
import { NavBar } from './NavBar'

// - Renders the bar over a faked API with tasks in the given statuses.

function task(id: string, status: Status): Task {
  return {
    id, provider: 'k2s', file_id: id, file_name: `${id}.rar`, size: 100, bytes_done: 0, speed: 0, eta: null,
    status, phase: null, message_key: null, message_params: {}, message: '', resumable: true, notice_key: null,
    file_exists: false, error: null, verified: null, created_at: 1, updated_at: 1, completed_at: null,
  }
}

function setup(statuses: Status[]) {
  vi.spyOn(api, 'tasks').mockResolvedValue(statuses.map((status, i) => task(`t${i}`, status)))
  vi.spyOn(api, 'storage').mockResolvedValue({ free_bytes: 2 ** 40, total_bytes: 4 * 2 ** 40 })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NavBar connected />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('NavBar', () => {
  it('counts failed tasks on the Downloads tab apart from active ones', async () => {
    setup(['failed', 'failed', 'downloading', 'canceled', 'paused'])
    const tab = await screen.findByRole('link', { name: /Downloads/ })
    expect(await screen.findByText('2 failed tasks')).toBeInTheDocument()
    expect(tab).toHaveTextContent('1 downloading or queued')
  })

  it('shows no failed count when nothing failed', async () => {
    setup(['downloading', 'canceled'])
    await screen.findByText('1 downloading or queued')
    expect(screen.queryByText(/failed task/)).not.toBeInTheDocument()
  })
})
