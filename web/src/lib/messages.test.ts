import { beforeEach, describe, expect, it } from 'vitest'
import type { Task } from '../api/types'
import i18n from '../i18n'
import { pageTitle, taskStatus } from './messages'

// - Checks the state word, detail line and detail tooltip the status cell shows for each status
//   and phase.

function task(change: Partial<Task> = {}): Task {
  return {
    id: 'job1', provider: 'k2s', file_id: 'aaa111', file_name: 'a.rar', size: 100, bytes_done: 10,
    speed: 0, eta: null, status: 'downloading', phase: null, message_key: null, message_params: {}, message: '',
    resumable: true, notice_key: null, file_exists: false, error: null, retryable: true, verified: null, created_at: 1, updated_at: 1,
    completed_at: null, ...change,
  }
}

const t = i18n.t.bind(i18n)

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('taskStatus', () => {
  it('says preparing while resolving, solving the captcha or getting links, with the step as detail', () => {
    expect(taskStatus(t, task({ phase: 'resolving', message_key: 'messages.resolving' })))
      .toEqual({ text: 'Preparing', detail: 'Reading file information', title: '' })
    expect(taskStatus(t, task({ phase: 'captcha', message_key: 'messages.captcha_attempt', message_params: { n: 3 } })))
      .toEqual({ text: 'Preparing', detail: 'Reading the captcha', title: 'Reading the captcha (try 3)' })
    expect(taskStatus(t, task({ phase: 'links', message_key: 'messages.links_generated', message_params: { done: 12, count: 20 } })))
      .toEqual({ text: 'Preparing', detail: 'Got 12 of 20 links', title: '' })
  })

  it('keeps the proxy and the connection kind out of the detail and in the tooltip', () => {
    expect(taskStatus(t, task({ phase: 'links', message_key: 'messages.requesting_key_proxy', message_params: { proxy: '1.2.3.4:8080' } })))
      .toEqual({ text: 'Preparing', detail: 'Requesting a download key', title: 'Requesting a download key via 1.2.3.4:8080' })
    expect(taskStatus(t, task({ phase: 'links', message_key: 'messages.requesting_key_direct' })))
      .toEqual({ text: 'Preparing', detail: 'Requesting a download key', title: 'Requesting a download key over the direct connection' })
  })

  it('shows a wait with its countdown as the state', () => {
    const status = taskStatus(t, task({ phase: 'waiting', message_key: 'messages.waiting_cooldown', message_params: { seconds: 252 } }))
    expect(status.text).toMatch(/^Waiting for the cooldown, .*4:12/)
    expect(status.detail).toBe('')
  })

  it('leaves the connection count out while downloading', () => {
    expect(taskStatus(t, task({ phase: 'downloading', message_key: 'messages.downloading', message_params: { count: 20 } })))
      .toEqual({ text: 'Downloading', detail: '', title: '' })
  })

  it('keeps other downloading messages as the detail', () => {
    expect(taskStatus(t, task({ phase: 'downloading', message_key: 'messages.remote_changed_restarting' })))
      .toEqual({ text: 'Downloading', detail: 'The remote file changed, downloading again from the start', title: '' })
  })

  it('says finishing while joining parts or checking the video', () => {
    expect(taskStatus(t, task({ phase: 'assembling', message_key: 'messages.assembling' })))
      .toEqual({ text: 'Finishing', detail: 'Joining parts', title: '' })
    expect(taskStatus(t, task({ phase: 'verifying', message_key: 'messages.verifying' })))
      .toEqual({ text: 'Finishing', detail: 'Checking the video', title: 'Checking the video with ffmpeg' })
  })

  it('gives a paused task its reason as the detail, except a plain pause', () => {
    expect(taskStatus(t, task({ status: 'paused', message_key: 'messages.paused_restart' })))
      .toEqual({ text: 'Paused', detail: 'The server restarted, so the download paused. Resume continues where it stopped.', title: '' })
    expect(taskStatus(t, task({ status: 'paused', message_key: 'messages.paused' })))
      .toEqual({ text: 'Paused', detail: '', title: '' })
    expect(taskStatus(t, task({ status: 'paused', message_key: 'messages.paused_legacy' })))
      .toEqual({ text: 'Paused', detail: '', title: '' })
  })

  it('shows the plain status otherwise', () => {
    expect(taskStatus(t, task({ status: 'queued', message_key: 'messages.waiting_slot' })))
      .toEqual({ text: 'Queued', detail: '', title: '' })
    expect(taskStatus(t, task({ status: 'canceled', message_key: 'messages.canceled' })))
      .toEqual({ text: 'Canceled', detail: '', title: '' })
  })

  it('uses the Traditional Chinese state words', async () => {
    await i18n.changeLanguage('zh-Hant-TW')
    expect(taskStatus(t, task({ phase: 'captcha', message_key: 'messages.captcha_attempt', message_params: { n: 3 } })))
      .toEqual({ text: '準備中', detail: '辨識驗證碼', title: '辨識驗證碼（第 3 次）' })
    expect(taskStatus(t, task({ phase: 'links', message_key: 'messages.requesting_key_proxy', message_params: { proxy: '1.2.3.4:8080' } })))
      .toEqual({ text: '準備中', detail: '取得下載授權', title: '透過 1.2.3.4:8080 取得下載授權' })
    expect(taskStatus(t, task({ phase: 'links', message_key: 'messages.requesting_key_direct' })))
      .toEqual({ text: '準備中', detail: '取得下載授權', title: '透過直接連線取得下載授權' })
    expect(taskStatus(t, task({ phase: 'verifying', message_key: 'messages.verifying' })))
      .toEqual({ text: '收尾中', detail: '檢查影片', title: '以 ffmpeg 檢查影片' })
    expect(taskStatus(t, task({ phase: 'assembling', message_key: 'messages.assembling' })).text).toBe('收尾中')
  })
})

describe('pageTitle', () => {
  it('counts active and failed tasks before the name', () => {
    expect(pageTitle(t, 0, 0, 'Hop fetch')).toBe('Hop fetch')
    expect(pageTitle(t, 2, 0, 'Hop fetch')).toBe('(2) Hop fetch')
    expect(pageTitle(t, 2, 1, 'Hop fetch')).toBe('(2) 1 failed – Hop fetch')
    expect(pageTitle(t, 0, 3, 'Hop fetch')).toBe('3 failed – Hop fetch')
  })

  it('uses the Traditional Chinese count', async () => {
    await i18n.changeLanguage('zh-Hant-TW')
    expect(pageTitle(t, 2, 1, 'Hop fetch')).toBe('(2) 1 個失敗 – Hop fetch')
  })
})
