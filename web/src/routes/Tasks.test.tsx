import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Tooltip } from 'radix-ui'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import providers from '../../../shared/providers.json'
import { api } from '../api/client'
import type { Task } from '../api/types'
import i18n from '../i18n'
import { Tasks } from './Tasks'

// - Renders the files page over a faked API with the tasks given, and fakes cancel and delete.

const GIB = 2 ** 30

function task(change: Partial<Task> = {}): Task {
  return {
    id: 'job1', provider: 'k2s', file_id: 'aaa111', file_name: 'a.rar', size: 2 * GIB, bytes_done: 1.31 * GIB,
    speed: 0, eta: null, status: 'paused', phase: null, message_key: null, message_params: {}, message: '',
    resumable: true, notice_key: null, file_exists: false, error: null, verified: null, created_at: 1, updated_at: 1,
    completed_at: null, ...change,
  }
}

function setup(tasks: Task[], path = '/tasks') {
  vi.spyOn(api, 'providers').mockResolvedValue(providers)
  vi.spyOn(api, 'tasks').mockResolvedValue(tasks)
  const cancel = vi.spyOn(api, 'cancel').mockResolvedValue(task({ status: 'canceled', bytes_done: 0 }))
  const remove = vi.spyOn(api, 'remove').mockResolvedValue(undefined)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Tooltip.Provider>
        <MemoryRouter initialEntries={[path]}>
          <Tasks />
        </MemoryRouter>
      </Tooltip.Provider>
    </QueryClientProvider>,
  )
  return { cancel, remove, user: userEvent.setup() }
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Tasks', () => {
  it('asks before canceling and states the bytes it discards', async () => {
    const { cancel, user } = setup([task()])
    await user.click(await screen.findByRole('button', { name: 'Cancel: a.rar' }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel download' })
    expect(dialog).toHaveTextContent('This discards the 1.31 GB downloaded so far.')
    expect(cancel).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Cancel download' }))
    await waitFor(() => expect(cancel).toHaveBeenCalledWith('job1'))
  })

  it('keeps the task when the cancel dialog is dismissed', async () => {
    const { cancel, user } = setup([task()])
    await user.click(await screen.findByRole('button', { name: 'Cancel: a.rar' }))
    await user.click(await screen.findByRole('button', { name: 'Keep' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(cancel).not.toHaveBeenCalled()
  })

  it('states the cost when deleting an unfinished task', async () => {
    const { remove, user } = setup([task()])
    await user.click(await screen.findByRole('button', { name: 'Delete: a.rar' }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete task' })
    expect(dialog).toHaveTextContent('This discards the 1.31 GB downloaded so far.')
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith('job1', false))
  })

  it('shows why a task is paused', async () => {
    setup([task({ message_key: 'messages.paused_restart' })])
    expect(await screen.findByText('The server restarted, so the download paused. Resume continues where it stopped.'))
      .toBeInTheDocument()
  })

  it('notes a task the server resumed after a restart', async () => {
    setup([task({ status: 'queued', message_key: 'messages.waiting_slot', notice_key: 'messages.resumed_restart' })])
    expect(await screen.findByText('Resumed after a server restart')).toBeInTheDocument()
  })

  it('offers every task when a filter matches nothing', async () => {
    const { user } = setup([task({ id: 'a', file_name: 'a.rar', status: 'completed' })], '/tasks?filter=failed')
    expect(await screen.findByText('No tasks match this filter')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Show all' }))
    expect(await screen.findByText('a.rar')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /All/ })).toBeChecked()
  })

  it('opens on the filter named in the address and drops it when another is chosen', async () => {
    const { user } = setup([task({ id: 'a', file_name: 'a.rar', status: 'failed' }),
      task({ id: 'b', file_name: 'b.rar', status: 'completed' })], '/tasks?filter=failed')
    const failed = await screen.findByRole('radio', { name: /Failed/ })
    expect(failed).toBeChecked()
    expect(screen.getByText('a.rar')).toBeInTheDocument()
    expect(screen.queryByText('b.rar')).not.toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /All/ }))
    expect(await screen.findByText('b.rar')).toBeInTheDocument()
  })

  it('lists failed tasks only under Failed and canceled ones only under All', async () => {
    const { user } = setup([task({ id: 'a', file_name: 'a.rar', status: 'failed' }),
      task({ id: 'b', file_name: 'b.rar', status: 'canceled' })], '/tasks?filter=failed')
    const failed = await screen.findByRole('radio', { name: /Failed/ })
    expect(failed).toHaveTextContent(/^Failed\s*1$/)
    expect(screen.getByText('a.rar')).toBeInTheDocument()
    expect(screen.queryByText('b.rar')).not.toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /All/ }))
    expect(await screen.findByText('b.rar')).toBeInTheDocument()
  })

  it('shows the state word with the step under it while downloading', async () => {
    setup([task({ status: 'downloading', phase: 'captcha', message_key: 'messages.captcha_attempt', message_params: { n: 3 } }),
      task({ id: 'job2', file_name: 'b.rar', status: 'downloading', phase: 'downloading',
        message_key: 'messages.downloading', message_params: { count: 20 } })])
    expect(await screen.findByText('Preparing')).toBeInTheDocument()
    expect(screen.getByText('Reading the captcha (try 3)')).toBeInTheDocument()
    expect(screen.getByText('Downloading')).toBeInTheDocument()
    expect(screen.queryByText(/connections/)).not.toBeInTheDocument()
  })

  it('shows speed and time left under the bar only while downloading', async () => {
    setup([task({ status: 'downloading', phase: 'downloading', speed: 4 * 2 ** 20, eta: 310 }),
      task({ id: 'job2', file_name: 'b.rar', status: 'paused', speed: 0 })])
    const rate = await screen.findByText('4.00 MB/s, 5:10 left')
    expect(rate.closest('td')).toContainElement(screen.getByRole('progressbar', { name: 'Progress of a.rar' }))
    expect(screen.getAllByText(/left$/)).toHaveLength(1)
    expect(screen.queryByRole('columnheader', { name: 'Speed' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Time left' })).not.toBeInTheDocument()
  })

  it('shows the speed alone while time left is unknown', async () => {
    setup([task({ status: 'downloading', phase: 'downloading', speed: 4 * 2 ** 20, eta: null })])
    expect(await screen.findByText('4.00 MB/s')).toBeInTheDocument()
    expect(screen.queryByText(/left$/)).not.toBeInTheDocument()
  })

  it('puts a failed task\'s error under its name', async () => {
    setup([task({ status: 'failed', error: { code: 'captcha_failed', key: 'errors.captcha_failed_ocr', params: {}, message: '' } })])
    const name = await screen.findByText('a.rar')
    const [statusCell] = name.closest('tr')!.querySelectorAll('td')
    expect(name.closest('td')).toHaveTextContent(/captcha/i)
    expect(statusCell).toHaveTextContent('Failed')
    expect(statusCell).not.toHaveTextContent(/captcha/i)
  })

  it('leaves the cost out when deleting a completed task', async () => {
    const { user } = setup([task({ status: 'completed', bytes_done: 2 * GIB, file_exists: true })])
    await user.click(await screen.findByRole('button', { name: 'Delete: a.rar' }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete task' })
    expect(dialog).not.toHaveTextContent('This discards')
    expect(screen.getByRole('checkbox', { name: 'Also delete the file on the NAS' })).toBeInTheDocument()
  })
})
