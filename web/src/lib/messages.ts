import type { TFunction } from 'i18next'
import type { CodedError, Task } from '../api/types'

// - Turns backend translation keys into text, falling back to the backend's own `message` and
//   then to a generic sentence; raw exception text never reaches the backend's answers.

export function errorText(t: TFunction, error: CodedError | null | undefined): string {
  if (!error) return ''
  return t(error.key, { ...error.params, defaultValue: error.message || t('errors.unknown') })
}

// - The status cell's text: the step detail while downloading, the plain status otherwise.
//   A failed task's reason is shown separately with `errorText`.
export function taskStatusText(t: TFunction, task: Task): string {
  if (task.status === 'downloading' && task.message_key) {
    return t(task.message_key, { ...task.message_params, defaultValue: task.message || t('status.downloading') })
  }
  return t(`status.${task.status}`)
}
