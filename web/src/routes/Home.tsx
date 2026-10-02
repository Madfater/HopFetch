import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { APP_NAME } from '../app-name'
import { ApiError, api } from '../api/client'
import type { Provider, Resolved, Task } from '../api/types'
import { Lamp, StatusLamp, type LampColor } from '../components/Lamp'
import { ProviderMark } from '../components/icons'
import { useToast } from '../components/toast-context'
import { RESOLVE_KEY, useResolve, type ResolveState } from '../hooks/useResolve'
import { formatBytes, formatStorage } from '../lib/format'
import { errorText } from '../lib/messages'
import { STORAGE_KEY, TASKS_KEY, upsertTask } from '../lib/tasks'
import { extractSingleUrl } from '../lib/url'
import controls from '../styles/controls.module.css'
import styles from './Home.module.css'

// - The download page: logo, the input slot, a preview of the resolved file, recent tasks.
// - A paste anywhere on the page, outside other fields, goes into the slot; so does a dropped
//   link. Exactly one URL in pasted text is taken; more than one is reported.
// - Enter starts the preview's main action, Esc clears the input.

const RECENT_COUNT = 5
const UNFINISHED = new Set(['queued', 'downloading', 'paused'])

type Plan =
  | { kind: 'download'; force: boolean }
  | { kind: 'blocked' }

// - What the preview offers: download, download again, or nothing, and why.
function planFor(data: Resolved, free: number): { plan: Plan; short: number } {
  const short = data.required_bytes == null ? 0 : Math.max(0, data.required_bytes - free)
  if (data.size == null || short > 0) return { plan: { kind: 'blocked' }, short }
  if (data.duplicate) {
    return data.duplicate.status === 'completed'
      ? { plan: { kind: 'download', force: true }, short }
      : { plan: { kind: 'blocked' }, short }
  }
  return { plan: { kind: 'download', force: false }, short }
}

function lampFor(state: ResolveState, plan: Plan | null, many: boolean): LampColor {
  if (many) return 'red'
  if (state.local.kind === 'empty') return 'off'
  if (state.local.kind !== 'matched' || state.error) return 'red'
  if (state.pending || !state.data) return 'amber'
  return plan?.kind === 'download' ? 'green' : 'red'
}

export function Home() {
  const { t, i18n } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()
  const client = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [input, setInput] = useState('')
  const [immediate, setImmediate] = useState(0)
  const [many, setMany] = useState(false)
  const [submitError, setSubmitError] = useState<ApiError | null>(null)

  const providers = useQuery({ queryKey: ['providers'], queryFn: api.providers, staleTime: Infinity })
  const tasks = useQuery({ queryKey: TASKS_KEY, queryFn: ({ signal }) => api.tasks(signal) })
  const storage = useQuery({ queryKey: STORAGE_KEY, queryFn: api.storage, staleTime: Infinity }).data
  const state = useResolve(input, providers.data ?? [], immediate)

  const free = storage?.free_bytes ?? state.data?.free_bytes ?? 0
  const planned = state.data ? planFor(state.data, free) : null
  const plan = planned?.plan ?? null

  const setFromPaste = useCallback((text: string) => {
    const found = extractSingleUrl(text)
    setSubmitError(null)
    if (found.kind === 'many') {
      setMany(true)
      return
    }
    setMany(false)
    setInput(found.kind === 'one' ? found.url : text.trim())
    setImmediate((n) => n + 1)
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target === inputRef.current) return
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
      const text = event.clipboardData?.getData('text') ?? ''
      if (!text) return
      event.preventDefault()
      setFromPaste(text)
    }
    document.addEventListener('paste', onPaste)
    return () => document.removeEventListener('paste', onPaste)
  }, [setFromPaste])

  const create = useMutation({
    mutationFn: ({ url, force }: { url: string; force: boolean }) => api.create(url, force),
    onSuccess: (task) => {
      client.setQueryData<Task[]>(TASKS_KEY, (list) => upsertTask(list, task))
      client.removeQueries({ queryKey: RESOLVE_KEY })
      toast(t('toast.started', { name: task.file_name ?? t('tasks.unnamed') }), 'success')
      setInput('')
      setMany(false)
      setSubmitError(null)
      inputRef.current?.focus()
    },
    onError: (err) => setSubmitError(err instanceof ApiError ? err : null),
  })

  const retry = useMutation({
    mutationFn: (id: string) => api.retry(id),
    onSuccess: (task) => {
      client.setQueryData<Task[]>(TASKS_KEY, (list) => upsertTask(list, task))
      client.removeQueries({ queryKey: RESOLVE_KEY })
      navigate(`/tasks?focus=${task.id}`)
    },
    onError: (err) => toast(err instanceof ApiError ? errorText(t, err.error) : t('errors.unknown'), 'error'),
  })

  const start = () => {
    if (many || state.local.kind !== 'matched' || plan?.kind !== 'download' || state.pending || create.isPending) return
    create.mutate({ url: state.local.url, force: plan.force })
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      start()
    } else if (event.key === 'Escape') {
      setInput('')
      setMany(false)
      setSubmitError(null)
    }
  }

  const onDrop = (event: DragEvent<HTMLElement>) => {
    const uris = event.dataTransfer.getData('text/uri-list')
    const text = uris
      ? uris.split(/\r?\n/).filter((line) => line && !line.startsWith('#')).join('\n')
      : event.dataTransfer.getData('text/plain')
    if (!text) return
    event.preventDefault()
    setFromPaste(text)
  }

  const lamp = lampFor(state, plan, many)
  const status = statusLine(t, state, many)
  const recent = (tasks.data ?? []).slice(0, RECENT_COUNT)

  return (
    <main className={styles.home}>
      <h1 className={styles.logo}>{APP_NAME}</h1>

      <label htmlFor="link" className="visually-hidden">
        {t('home.inputLabel')}
      </label>
      <div className={styles.slot} onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
        <input
          ref={inputRef}
          id="link"
          className={styles.input}
          type="text"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          autoFocus
          placeholder={t('home.placeholder')}
          value={input}
          aria-describedby="link-status"
          aria-invalid={lamp === 'red' ? true : undefined}
          onChange={(event) => {
            setInput(event.target.value)
            setMany(false)
            setSubmitError(null)
          }}
          onPaste={(event) => {
            const text = event.clipboardData.getData('text')
            const found = extractSingleUrl(text)
            if (found.kind === 'none') return
            event.preventDefault()
            setFromPaste(text)
          }}
          onKeyDown={onKeyDown}
        />
        <Lamp color={lamp} />
        <span className="visually-hidden">{t(`home.lamp.${lampName(lamp)}`)}</span>
      </div>
      <p id="link-status" className={`${styles.status} ${status.error ? styles.statusError : ''}`} aria-live="polite">
        {status.text}
      </p>

      {!many && state.data && state.local.kind === 'matched' && planned && (
        <Preview
          data={state.data}
          provider={state.local.provider}
          free={free}
          short={planned.short}
          plan={planned.plan}
          locale={i18n.language}
          busy={create.isPending || retry.isPending}
          submitError={submitError}
          onDownload={start}
          onRetry={(id) => retry.mutate(id)}
        />
      )}

      {recent.length > 0 && (
        <section className={styles.recent} aria-labelledby="recent-title">
          <div className={styles.recentHead}>
            <h2 id="recent-title" className={styles.recentTitle}>
              {t('home.recent')}
            </h2>
            <Link to="/tasks">{t('home.viewAll')}</Link>
          </div>
          <ul>
            {recent.map((task) => (
              <li key={task.id}>
                <button type="button" className={styles.recentItem} onClick={() => navigate(`/tasks?focus=${task.id}`)}>
                  <span className={styles.recentName}>{task.file_name ?? t('tasks.unnamed')}</span>
                  <StatusLamp status={task.status} text={t(`status.${task.status}`)} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  )
}

function lampName(lamp: LampColor): string {
  return { off: 'idle', amber: 'checking', green: 'ready', red: 'blocked', steel: 'idle' }[lamp]
}

function statusLine(t: ReturnType<typeof useTranslation>['t'], state: ResolveState, many: boolean): { text: string; error: boolean } {
  if (many) return { text: t('home.manyUrls'), error: true }
  switch (state.local.kind) {
    case 'empty':
      return { text: '', error: false }
    case 'invalid':
      return { text: t('errors.invalid_url'), error: true }
    case 'unsupported':
      return { text: t('errors.unsupported'), error: true }
  }
  if (state.error) {
    const error = state.error instanceof ApiError ? state.error.error : null
    return { text: error ? errorText(t, error) : t('errors.unknown'), error: true }
  }
  if (state.pending) return { text: t('home.checking'), error: false }
  return { text: '', error: false }
}

interface PreviewProps {
  data: Resolved
  provider: Provider
  free: number
  short: number
  plan: Plan
  locale: string
  busy: boolean
  submitError: ApiError | null
  onDownload: () => void
  onRetry: (id: string) => void
}

function Preview({ data, provider, free, short, plan, locale, busy, submitError, onDownload, onRetry }: PreviewProps) {
  const { t } = useTranslation()
  const duplicate = data.duplicate
  const notes: { text: string; error: boolean }[] = []
  if (data.size == null) notes.push({ text: t('preview.sizeUnknownHint'), error: true })
  if (short > 0) notes.push({ text: t('preview.short', { size: formatBytes(locale, short) }), error: true })
  if (duplicate && UNFINISHED.has(duplicate.status)) notes.push({ text: t('preview.duplicateActive'), error: true })
  if (duplicate && (duplicate.status === 'failed' || duplicate.status === 'canceled')) {
    notes.push({ text: t('preview.duplicateFailed'), error: true })
  }
  if (duplicate?.status === 'completed') notes.push({ text: t('preview.duplicateCompleted'), error: false })
  if (submitError) notes.push({ text: errorText(t, submitError.error), error: true })

  return (
    <section className={styles.preview} aria-label={data.file_name}>
      <div className={styles.file}>
        <ProviderMark icon={provider.icon} />
        <p className={styles.fileName}>{data.file_name}</p>
      </div>
      <dl className={styles.facts}>
        <div className={styles.fact}>
          <dt>{t('preview.size')}</dt>
          <dd className="num">{data.size == null ? t('preview.sizeUnknown') : formatBytes(locale, data.size)}</dd>
        </div>
        <div className={styles.fact}>
          <dt>{t('nav.storage')}</dt>
          <dd className="num">{formatStorage(locale, free)}</dd>
        </div>
        <div className={styles.fact}>
          <dt className="visually-hidden">{t('tasks.column.provider')}</dt>
          <dd>{provider.name}</dd>
        </div>
      </dl>
      {notes.map((note) => (
        <p key={note.text} className={`${styles.note} ${note.error ? styles.noteError : ''}`}>
          {note.text}
        </p>
      ))}
      <div className={styles.actions}>
        {plan.kind === 'download' && (
          <button type="button" className={`${controls.button} ${controls.primary}`} onClick={onDownload} disabled={busy}>
            {plan.force ? t('preview.downloadAnyway') : t('preview.download')}
          </button>
        )}
        {duplicate && (duplicate.status === 'failed' || duplicate.status === 'canceled') && (
          <button type="button" className={controls.button} onClick={() => onRetry(duplicate.task_id)} disabled={busy}>
            {t('preview.retry')}
          </button>
        )}
        {duplicate && (
          <Link className={controls.button} to={`/tasks?focus=${duplicate.task_id}`}>
            {t('preview.view')}
          </Link>
        )}
        {plan.kind === 'download' && <span className={styles.keys}>{t('preview.keys')}</span>}
      </div>
    </section>
  )
}

