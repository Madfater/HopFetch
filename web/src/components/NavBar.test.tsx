import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { Status, Task } from '../api/types'
import i18n from '../i18n'
import { NavBar } from './NavBar'

// - Renders the bar over a faked API with tasks in the given statuses; `unfixable` is a failed
//   task no retry can fix.

function task(id: string, given: Status | 'unfixable'): Task {
  const status = given === 'unfixable' ? 'failed' : given
  return {
    id, provider: 'k2s', file_id: id, file_name: `${id}.rar`, size: 100, bytes_done: 0, speed: 0, eta: null,
    status, phase: null, message_key: null, message_params: {}, message: '', resumable: true, notice_key: null,
    file_exists: false, error: null, retryable: given !== 'unfixable', verified: null, created_at: 1, updated_at: 1, completed_at: null,
  }
}

function setup(statuses: (Status | 'unfixable')[], storage?: Promise<{ free_bytes: number; total_bytes: number }>) {
  vi.spyOn(api, 'tasks').mockResolvedValue(statuses.map((status, i) => task(`t${i}`, status)))
  vi.spyOn(api, 'storage').mockReturnValue(storage ?? Promise.resolve({ free_bytes: 2 ** 40, total_bytes: 4 * 2 ** 40 }))
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
    setup(['failed', 'failed', 'unfixable', 'downloading', 'canceled', 'paused'])
    const tab = await screen.findByRole('link', { name: /Downloads/ })
    expect(await screen.findByText('2 failed tasks')).toBeInTheDocument()
    expect(tab).toHaveTextContent('1 downloading or queued')
    expect(tab).toHaveAccessibleName(/^Downloads, ?1 downloading or queued, ?2 failed tasks$/)
  })

  it('says free space is being checked until the first answer, then shows it', async () => {
    let answer: (value: { free_bytes: number; total_bytes: number }) => void = () => {}
    setup([], new Promise((resolve) => { answer = resolve }))
    expect(screen.getByText('Checking NAS free space')).toBeInTheDocument()
    expect(screen.queryByText('NAS free space unknown')).not.toBeInTheDocument()
    answer({ free_bytes: 11 * 2 ** 30, total_bytes: 4 * 2 ** 40 })
    expect(await screen.findAllByText('11 GB')).not.toHaveLength(0)
    expect(screen.getByText('free')).toBeInTheDocument()
    expect(screen.queryByText('Checking NAS free space')).not.toBeInTheDocument()
  })

  it('says free space is unknown only when the request fails', async () => {
    setup([], Promise.reject(new Error('down')))
    expect(await screen.findByText('NAS free space unknown')).toBeInTheDocument()
  })

  it('shows no failed count when nothing failed', async () => {
    setup(['downloading', 'canceled', 'unfixable'])
    await screen.findByText('1 downloading or queued')
    expect(screen.queryByText(/failed task/)).not.toBeInTheDocument()
  })
})
