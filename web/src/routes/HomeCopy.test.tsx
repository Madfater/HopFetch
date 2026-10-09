import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Tooltip } from 'radix-ui'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import providers from '../../../shared/providers.json'
import { api } from '../api/client'
import type { Resolved, Task } from '../api/types'
import { NavBar } from '../components/NavBar'
import { ToastProvider } from '../components/Toasts'
import i18n from '../i18n'
import { Home } from './Home'
import { Tasks } from './Tasks'

// - Renders the navigation bar and the download page over a faked API, with the app's toast and
//   tooltip providers, and checks the text that says what the page takes, where files go, and
//   what each page is called.
// - Each link's file id picks its answer; `pending` ids never answer, to hold the checking state.

const FREE = 100 * 2 ** 30
const PROMISE = 'Saves to the NAS download folder. You can close this page; the download continues on the server.'
const PROMISE_ZH = '完成後會存到 NAS 的下載資料夾。可以關閉這頁，下載會在伺服器上繼續。'
const link = (id: string) => `https://k2s.cc/file/${id}/${id}.rar`

function file(id: string, change: Partial<Resolved> = {}): Resolved {
  return {
    provider: 'k2s', file_id: id, file_name: `${id}.rar`, size: 2 ** 30, resumable: true,
    duplicate: null, free_bytes: FREE, required_bytes: 2 * 2 ** 30, ...change,
  }
}

function task(id: string): Task {
  return {
    id, provider: 'k2s', file_id: id, file_name: `${id}.rar`, size: 2 ** 30, bytes_done: 0, speed: 0, eta: null,
    status: 'queued', phase: null, message_key: null, message_params: {}, message: '', resumable: true,
    notice_key: null, file_exists: false, error: null, retryable: true, verified: null, created_at: 1, updated_at: 1,
    completed_at: null,
  }
}

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <Tooltip.Provider>
        <ToastProvider>
          <MemoryRouter>{children}</MemoryRouter>
        </ToastProvider>
      </Tooltip.Provider>
    </QueryClientProvider>
  )
}

function setup(answers: Record<string, Resolved | 'pending'> = {}) {
  vi.spyOn(api, 'providers').mockResolvedValue(providers)
  vi.spyOn(api, 'tasks').mockResolvedValue([])
  vi.spyOn(api, 'storage').mockResolvedValue({ free_bytes: FREE, total_bytes: 4 * FREE })
  vi.spyOn(api, 'resolve').mockImplementation((url) => {
    const answer = answers[url.split('/')[4]] ?? file(url.split('/')[4])
    return answer === 'pending' ? new Promise<Resolved>(() => {}) : Promise.resolve(answer)
  })
  vi.spyOn(api, 'create').mockImplementation(async (url) => task(url.split('/')[4]))
  render(wrap(<><NavBar connected /><Home /></>))
  return userEvent.setup()
}

async function paste(user: ReturnType<typeof userEvent.setup>, text: string) {
  await vi.waitFor(() => expect(api.providers).toHaveBeenCalled())
  await user.click(screen.getByRole('textbox'))
  await user.paste(text)
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
    await paste(user, 'https://example.com/file/abc')
    await screen.findByText('Only Keep2Share and MEGA links are supported.')
  })

  it('says where a downloadable file goes, and the start toast says the page can be closed', async () => {
    const user = setup()
    await paste(user, link('a1'))
    await screen.findByRole('region', { name: 'a1.rar' })
    expect(screen.getByText(PROMISE)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Download' }))
    await screen.findByText('Download started: a1.rar. You can close this page.')
  })

  it('leaves the promise out when the file cannot be downloaded', async () => {
    const user = setup({ a2: file('a2', { required_bytes: 2 * FREE }) })
    await paste(user, link('a2'))
    await screen.findByRole('region', { name: 'a2.rar' })
    expect(screen.queryByText(PROMISE)).toBeNull()
  })

  it('says the promise on a batch, and its toast says the page can be closed', async () => {
    const user = setup()
    await paste(user, `${link('b1')} ${link('b2')}`)
    const card = await screen.findByRole('region', { name: 'Batch of 2 links' })
    await within(card).findByText(PROMISE)
    await user.click(within(card).getByRole('button', { name: 'Download 2 files' }))
    await screen.findByText('Started 2 downloads. You can close this page.')
  })

  it('names the task list Downloads in the navigation and on its page', async () => {
    setup()
    expect(within(screen.getByRole('navigation')).getByRole('link', { name: /^Downloads/ })).toBeTruthy()
    render(wrap(<Tasks />))
    expect(await screen.findByRole('heading', { level: 1, name: 'Downloads' })).toBeTruthy()
  })
})

describe('Home copy in Traditional Chinese', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('zh-Hant-TW')
  })

  it('says the promise and the start toast', async () => {
    const user = setup()
    await paste(user, link('c1'))
    await screen.findByText(PROMISE_ZH)
    await user.click(screen.getByRole('button', { name: '下載' }))
    await screen.findByText('已開始下載「c1.rar」，可以關閉這頁。')
  })

  it('names the supported sites in the empty input and for a link from another site', async () => {
    const user = setup()
    await vi.waitFor(() =>
      expect(screen.getByRole('textbox')).toHaveAttribute('placeholder', '貼上 Keep2Share 或 MEGA 的分享連結'),
    )
    await paste(user, 'https://example.com/file/abc')
    await screen.findByText('目前只支援 Keep2Share 和 MEGA 的連結。')
  })

  it('says 檢查 while a link is being checked', async () => {
    const user = setup({ c2: 'pending' })
    await paste(user, link('c2'))
    await screen.findByText('正在檢查連結')
    expect(screen.getByText('檢查中')).toBeTruthy()
  })

  it('names the task list 下載清單 and the preview link 查看任務', async () => {
    const user = setup({ c3: file('c3', { duplicate: { task_id: 'old1', status: 'queued' } }) })
    expect(within(screen.getByRole('navigation')).getByRole('link', { name: /^下載清單/ })).toBeTruthy()
    await paste(user, link('c3'))
    expect(await screen.findByRole('link', { name: '查看任務' })).toBeTruthy()
  })
})
