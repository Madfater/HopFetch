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
}

// - The status cell's two lines: `text` is the state beside the lamp, `detail` the step behind
//   it, empty when there is nothing to add. A failed task's reason is shown separately with
//   `errorText`.
// - While downloading, the phase picks a state word: preparing for resolving, captcha and links,
//   finishing for assembling and verifying. A wait shows its message as the state, since the
//   countdown is what the user needs.
// - The connection count of `messages.downloading` is left out; other downloading messages,
//   such as a restart after the remote file changed, stay as the detail.
// - A paused task shows its reason as the detail, unless the reason is a plain pause, which
//   `messages.paused` and `messages.paused_legacy` both are.
// - A failed task that no retry can fix reads "cannot be downloaded" instead of "failed".
export function taskStatus(t: TFunction, task: Task): StatusText {
  const status = t(isUnfixable(task) ? 'status.unfixable' : `status.${task.status}`)
  const message = task.message_key
    ? t(task.message_key, { ...task.message_params, defaultValue: task.message || '' })
    : ''
  if (task.status === 'paused') {
    const plain = task.message_key === 'messages.paused' || task.message_key === 'messages.paused_legacy'
    return { text: status, detail: plain ? '' : message }
  }
  if (task.status !== 'downloading') return { text: status, detail: '' }
  switch (task.phase) {
    case 'waiting':
      return { text: message || status, detail: '' }
    case 'resolving':
    case 'captcha':
    case 'links':
      return { text: t('phaseState.preparing'), detail: message }
    case 'assembling':
    case 'verifying':
      return { text: t('phaseState.finishing'), detail: message }
    default:
      return { text: status, detail: task.message_key === 'messages.downloading' ? '' : message }
  }
}

// - The tab title: `(n)` for the tasks queued or downloading, then the failed count when any
//   task failed, then the app name, as in `(2) 1 failed – Hop fetch`.
export function pageTitle(t: TFunction, active: number, failed: number, name: string): string {
  const parts = [active > 0 ? `(${active})` : '', failed > 0 ? `${t('nav.titleFailed', { count: failed })} –` : '', name]
  return parts.filter(Boolean).join(' ')
}
