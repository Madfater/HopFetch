import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import providers from '../../../shared/providers.json'
import { api } from '../api/client'
import type { Status, Task } from '../api/types'
import i18n from '../i18n'
import { Home } from './Home'

// - Renders the download page over a faked API with tasks in the given statuses.

function task(id: string, status: Status): Task {
  return {
    id, provider: 'k2s', file_id: id, file_name: `${id}.rar`, size: 100, bytes_done: 0, speed: 0, eta: null,
    status, phase: null, message_key: null, message_params: {}, message: '', resumable: true, notice_key: null,
    file_exists: false, error: null, retryable: true, verified: null, created_at: 1, updated_at: 1, completed_at: null,
  }
}

function setup(statuses: Status[]) {
  vi.spyOn(api, 'providers').mockResolvedValue(providers)
  vi.spyOn(api, 'tasks').mockResolvedValue(statuses.map((status, i) => task(`t${i}`, status)))
  vi.spyOn(api, 'storage').mockResolvedValue({ free_bytes: 2 ** 40, total_bytes: 4 * 2 ** 40 })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Home />
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

describe('Home attention line', () => {
  it('counts failed tasks and links to the failed filter', async () => {
    setup(['failed', 'completed', 'failed'])
    const link = await screen.findByRole('link', { name: '2 tasks need attention' })
    expect(link).toHaveAttribute('href', '/tasks?filter=failed')
  })

  it('is absent when nothing failed', async () => {
    setup(['completed', 'canceled'])
    await screen.findByRole('heading', { name: 'Recent tasks' })
    expect(screen.queryByText(/need attention|needs attention/)).not.toBeInTheDocument()
  })
})
