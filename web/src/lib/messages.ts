import type { TFunction } from 'i18next'
import type { CodedError, Task } from '../api/types'
import { isUnfixable } from './tasks'

// - Turns backend translation keys into text, falling back to the backend's own `message` and
//   then to a generic sentence; raw exception text never reaches the backend's answers.

export function errorText(t: TFunction, error: CodedError | null | undefined): string {
  if (!error) return ''
  return t(error.key, { ...error.params, defaultValue: error.message || t('errors.unknown') })
}

export interface StatusText {
  text: string
  detail: string
  title: string
}

// - The word for a task's status; a failed task that no retry can fix reads "cannot be
//   downloaded" instead of "failed".
export function statusWord(t: TFunction, task: Task): string {
  return t(isUnfixable(task) ? 'status.unfixable' : `status.${task.status}`)
}

// - The status cell's two lines: `text` is the state beside the lamp, `detail` the step behind
//   it, empty when there is nothing to add. A failed task's reason is shown separately with
//   `errorText`.
// - `title` is the tooltip on the detail line, empty unless the detail leaves something out.
//   A step whose message names a mechanic, such as the proxy, the captcha try or ffmpeg, has
//   a short `stepDetail.*` form; the detail shows that form and `title` the full message.
// - While downloading, the phase picks a state word: preparing for resolving, captcha and links,
//   finishing for assembling and verifying. A wait shows its message as the state, since the
//   countdown is what the user needs.
// - The connection count of `messages.downloading` is left out; other downloading messages,
//   such as a restart after the remote file changed, stay as the detail.
// - A paused task shows its reason as the detail, unless the reason is a plain pause, which
//   `messages.paused` and `messages.paused_legacy` both are.
export function taskStatus(t: TFunction, task: Task): StatusText {
  const status = statusWord(t, task)
  const message = task.message_key
    ? t(task.message_key, { ...task.message_params, defaultValue: task.message || '' })
    : ''
  const step = (text: string): StatusText => {
    const name = task.message_key?.startsWith('messages.') ? task.message_key.slice('messages.'.length) : ''
    const short = name ? t(`stepDetail.${name}`, { defaultValue: '' }) : ''
    return short ? { text, detail: short, title: message } : { text, detail: message, title: '' }
  }
  if (task.status === 'paused') {
    const plain = task.message_key === 'messages.paused' || task.message_key === 'messages.paused_legacy'
    return { text: status, detail: plain ? '' : message, title: '' }
  }
  if (task.status !== 'downloading') return { text: status, detail: '', title: '' }
  switch (task.phase) {
    case 'waiting':
      return { text: message || status, detail: '', title: '' }
    case 'resolving':
    case 'captcha':
    case 'links':
      return step(t('phaseState.preparing'))
    case 'assembling':
    case 'verifying':
      return step(t('phaseState.finishing'))
    default:
      return { text: status, detail: task.message_key === 'messages.downloading' ? '' : message, title: '' }
  }
}

// - The tab title: `(n)` for the tasks queued or downloading, then the failed count when any
//   task failed, then the app name, as in `(2) 1 failed – Hop fetch`.
export function pageTitle(t: TFunction, active: number, failed: number, name: string): string {
  const parts = [active > 0 ? `(${active})` : '', failed > 0 ? `${t('nav.titleFailed', { count: failed })} –` : '', name]
  return parts.filter(Boolean).join(' ')
}
