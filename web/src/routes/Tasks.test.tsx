import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Tooltip } from 'radix-ui'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import providers from '../../../shared/providers.json'
import { ApiError, api } from '../api/client'
import type { Task } from '../api/types'
import { ToastContext } from '../components/toast-context'
import i18n from '../i18n'
import { copyText } from '../lib/clipboard'
import { Tasks } from './Tasks'
import styles from './Tasks.module.css'

// - Renders the files page over a faked API with the tasks given, and fakes cancel and delete.
// - Toasts go to a spy, and the clipboard is a mock.

vi.mock('../lib/clipboard', () => ({ copyText: vi.fn() }))

const GIB = 2 ** 30

function task(change: Partial<Task> = {}): Task {
  return {
    id: 'job1', url: 'https://k2s.cc/file/aaa111', provider: 'k2s', file_id: 'aaa111', file_name: 'a.rar', size: 2 * GIB, bytes_done: 1.31 * GIB,
    speed: 0, eta: null, status: 'paused', phase: null, message_key: null, message_params: {}, message: '',
    resumable: true, notice_key: null, file_exists: false, error: null, retryable: true, verified: null, created_at: 1, updated_at: 1,
    completed_at: null, ...change,
  }
}

function setup(tasks: Task[], path = '/tasks') {
  vi.spyOn(api, 'providers').mockResolvedValue(providers)
  vi.spyOn(api, 'tasks').mockResolvedValue(tasks)
  const cancel = vi.spyOn(api, 'cancel').mockResolvedValue(task({ status: 'canceled', bytes_done: 0 }))
  const remove = vi.spyOn(api, 'remove').mockResolvedValue(undefined)
  const toast = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ToastContext.Provider value={toast}>
        <Tooltip.Provider>
          <MemoryRouter initialEntries={[path]}>
            <Tasks />
          </MemoryRouter>
        </Tooltip.Provider>
      </ToastContext.Provider>
    </QueryClientProvider>,
  )
  return { cancel, remove, toast, user: userEvent.setup() }
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.mocked(copyText).mockReset()
})

const REFUSED = new ApiError(409, { code: 'invalid_state', key: 'errors.invalid_state_retry', params: {}, message: '' })

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

  it('shows the state word with the step under it while downloading, the try count only in its tooltip', async () => {
    setup([task({ status: 'downloading', phase: 'captcha', message_key: 'messages.captcha_attempt', message_params: { n: 3 } }),
      task({ id: 'job2', file_name: 'b.rar', status: 'downloading', phase: 'downloading',
        message_key: 'messages.downloading', message_params: { count: 20 } })])
    expect(await screen.findByText('Preparing')).toBeInTheDocument()
    expect(screen.getByText('Reading the captcha')).toHaveAttribute('title', 'Reading the captcha (try 3)')
    expect(screen.queryByText(/try 3/)).not.toBeInTheDocument()
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

  it('marks the host before the file name instead of in a column', async () => {
    setup([task(), task({ id: 'job2', provider: 'mega', file_name: 'b.zip' })])
    const mark = await screen.findByRole('img', { name: 'MEGA' })
    expect(mark).toHaveAttribute('title', 'MEGA')
    expect(mark.closest('td')).toHaveTextContent('b.zip')
    expect(screen.getByRole('img', { name: 'Keep2Share' }).closest('td')).toHaveTextContent('a.rar')
    expect(screen.queryByRole('columnheader', { name: 'Host' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('columnheader')).toHaveLength(5)
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

  it('shows a failure no retry can fix as its own outcome with delete as the only action', async () => {
    setup([task({ status: 'failed', retryable: false,
      error: { code: 'not_found', key: 'errors.not_found', params: {}, message: '' } })])
    const name = await screen.findByText('a.rar')
    const row = name.closest('tr')!
    const [statusCell] = row.querySelectorAll('td')
    expect(statusCell).toHaveTextContent('Cannot be downloaded')
    expect(statusCell).not.toHaveTextContent('Failed')
    expect(screen.getByText(/This file was not found/).className).not.toContain(styles.subError)
    expect(screen.getByRole('button', { name: 'Delete: a.rar' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry: a.rar' })).not.toBeInTheDocument()
  })

  it('draws a failure no retry can fix on a neutral track with a dash for its percent', async () => {
    setup([task({ id: 'a', file_name: 'a.rar', status: 'failed', retryable: false, size: null, bytes_done: 0 }),
      task({ id: 'b', file_name: 'b.rar', status: 'failed', bytes_done: 0 })])
    const plain = await screen.findByRole('progressbar', { name: 'Progress of a.rar' })
    expect(plain.className).not.toContain(styles.trackFailed)
    expect(plain).toHaveAttribute('aria-valuetext', 'Cannot be downloaded')
    expect(plain.closest('tr')!.querySelector(`.${styles.percent}`)).toHaveTextContent('—')
    expect(plain.closest('tr')!.querySelector(`.${styles.cellSize}`)).toHaveTextContent('—Size unknown')
    const red = screen.getByRole('progressbar', { name: 'Progress of b.rar' })
    expect(red.className).toContain(styles.trackFailed)
    expect(red.closest('tr')!.querySelector(`.${styles.percent}`)).toHaveTextContent('0%')
  })

  it('groups cancel with delete as a stop action, apart from resume', async () => {
    setup([task()])
    const cancel = await screen.findByRole('button', { name: 'Cancel: a.rar' })
    const resume = screen.getByRole('button', { name: 'Resume: a.rar' })
    const remove = screen.getByRole('button', { name: 'Delete: a.rar' })
    expect(cancel.parentElement).toBe(remove.parentElement)
    expect(cancel.parentElement).toHaveClass(styles.discard)
    expect(resume.parentElement).not.toBe(cancel.parentElement)
    expect(cancel.querySelector('path')).toHaveAttribute('d', 'M4.5 4.5h7v7h-7z')
  })

  it('offers retry on a failure a retry can fix and on a canceled task', async () => {
    setup([task({ id: 'a', file_name: 'a.rar', status: 'failed' }), task({ id: 'b', file_name: 'b.rar', status: 'canceled' })])
    expect(await screen.findByRole('button', { name: 'Retry: a.rar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry: b.rar' })).toBeInTheDocument()
  })

  it('lists a failure no retry can fix only under All', async () => {
    const { user } = setup([task({ id: 'a', file_name: 'a.rar', status: 'failed', retryable: false })], '/tasks?filter=failed')
    expect(await screen.findByRole('radio', { name: /Failed/ })).toHaveTextContent(/^Failed\s*0$/)
    expect(screen.queryByText('a.rar')).not.toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /All/ }))
    expect(await screen.findByText('a.rar')).toBeInTheDocument()
  })

  it('reads the progress bar as percent, bytes of the size, and state', async () => {
    setup([task(), task({ id: 'job2', file_name: 'b.rar', size: null, status: 'queued', bytes_done: 0 })])
    expect(await screen.findByRole('progressbar', { name: 'Progress of a.rar' }))
      .toHaveAttribute('aria-valuetext', '66%, 1.31 GB of 2.00 GB, Paused')
    expect(screen.getByRole('progressbar', { name: 'Progress of b.rar' }))
      .toHaveAttribute('aria-valuetext', '0 B downloaded, Queued')
  })

  it('reads the progress bar in Chinese', async () => {
    await i18n.changeLanguage('zh-Hant-TW')
    setup([task()])
    expect(await screen.findByRole('progressbar', { name: 'a.rar 的進度' }))
      .toHaveAttribute('aria-valuetext', '66%，已下載 1.31 GB，共 2.00 GB，已暫停')
  })

  it('leaves the cost out when deleting a completed task', async () => {
    const { user } = setup([task({ status: 'completed', bytes_done: 2 * GIB, file_exists: true })])
    await user.click(await screen.findByRole('button', { name: 'Delete: a.rar' }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete task' })
    expect(dialog).not.toHaveTextContent('This discards')
    expect(screen.getByRole('checkbox', { name: 'Also delete the file on the NAS' })).toBeInTheDocument()
  })

  it('notes a completed file that is gone neutrally and removes only its list entry', async () => {
    const { remove, user } = setup([task({ status: 'completed', bytes_done: 2 * GIB, file_exists: false })])
    const note = await screen.findByText('Moved or deleted from the NAS', { exact: false })
    expect(note.className).not.toMatch(/subError/)
    await user.click(screen.getByRole('button', { name: 'Remove from list: a.rar' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(remove).toHaveBeenCalledWith('job1', false)
    await waitFor(() => expect(screen.queryByText('a.rar')).not.toBeInTheDocument())
  })

  it('waits on a running list removal', async () => {
    const { remove, user } = setup([task({ status: 'completed', bytes_done: 2 * GIB, file_exists: false })])
    remove.mockReturnValue(new Promise(() => {}))
    const button = await screen.findByRole('button', { name: 'Remove from list: a.rar' })
    await user.click(button)
    expect(button).toBeDisabled()
    await user.click(button)
    expect(remove).toHaveBeenCalledTimes(1)
  })

  it('resumes every paused task from Unfinished, one request each, and reports it', async () => {
    const { toast, user } = setup([
      task({ id: 'a', file_name: 'a.rar' }),
      task({ id: 'b', file_name: 'b.rar', status: 'downloading' }),
      task({ id: 'c', file_name: 'c.rar' }),
    ], '/tasks?filter=active')
    const resume = vi.spyOn(api, 'resume').mockImplementation(async (id) => task({ id, status: 'queued', updated_at: 2 }))
    await user.click(await screen.findByRole('button', { name: 'Resume all (2)' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Resumed 2 tasks'))
    expect(resume.mock.calls).toEqual([['a'], ['c']])
    expect(screen.queryByRole('button', { name: /Resume all/ })).not.toBeInTheDocument()
  })

  it('offers resume all only under Unfinished and only with paused tasks', async () => {
    const { user } = setup([task({ id: 'a', status: 'downloading' }), task({ id: 'b', status: 'failed' })])
    await screen.findByRole('radio', { name: /All/ })
    expect(screen.queryByRole('button', { name: /all \(/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: /Unfinished/ }))
    expect(screen.queryByRole('button', { name: /Resume all/ })).not.toBeInTheDocument()
  })

  it('counts only failures a retry can fix and reports the ones refused', async () => {
    const { toast, user } = setup([
      task({ id: 'a', file_name: 'a.rar', status: 'failed' }),
      task({ id: 'b', file_name: 'b.rar', status: 'failed', retryable: false }),
      task({ id: 'c', file_name: 'c.rar', status: 'failed' }),
      task({ id: 'd', file_name: 'd.rar', status: 'canceled' }),
    ], '/tasks?filter=failed')
    const retry = vi.spyOn(api, 'retry').mockImplementation(async (id) => {
      if (id === 'c') throw REFUSED
      return task({ id, status: 'queued', updated_at: 2 })
    })
    await user.click(await screen.findByRole('button', { name: 'Retry all (2)' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith(
      'Retrying 1, 1 could not be retried: Only failed or canceled tasks can be retried.', 'error'))
    expect(retry.mock.calls).toEqual([['a'], ['c']])
  })

  it('says when no task of the batch went through', async () => {
    const { toast, user } = setup([task({ id: 'a', status: 'failed' }), task({ id: 'b', status: 'failed' })],
      '/tasks?filter=failed')
    vi.spyOn(api, 'retry').mockRejectedValueOnce(REFUSED).mockRejectedValueOnce(new Error('boom'))
    await user.click(await screen.findByRole('button', { name: 'Retry all (2)' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('None of the 2 tasks could be retried', 'error'))
  })

  it('copies a task\'s source link and confirms it', async () => {
    vi.mocked(copyText).mockResolvedValue(true)
    const { toast, user } = setup([task()])
    await user.click(await screen.findByRole('button', { name: 'Copy link: a.rar' }))
    expect(copyText).toHaveBeenCalledWith('https://k2s.cc/file/aaa111')
    expect(await screen.findByRole('status')).toHaveTextContent('Link copied')
    expect(toast).not.toHaveBeenCalled()
  })

  it('raises an error when the link cannot be copied', async () => {
    vi.mocked(copyText).mockResolvedValue(false)
    const { toast, user } = setup([task()])
    await user.click(await screen.findByRole('button', { name: 'Copy link: a.rar' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Could not copy the link: the browser blocked the clipboard.', 'error'))
  })
})
