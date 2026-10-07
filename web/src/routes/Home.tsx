import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { APP_NAME } from '../app-name'
import { ApiError, api } from '../api/client'
import type { Provider, Resolved, Task } from '../api/types'
import { Lamp, StatusLamp, type LampColor } from '../components/Lamp'
import { ProviderMark } from '../components/icons'
import { useToast } from '../components/toast-context'
import { useBatch } from '../hooks/useBatch'
import { useNewIds } from '../hooks/useNewIds'
import { useResolve, type ResolveState } from '../hooks/useResolve'
import { useProviders, useTasks } from '../hooks/useTasks'
import { formatBytes, formatList, formatPercent, formatStorage } from '../lib/format'
import { batchView, UNFINISHED, type BatchView, type Outcome } from '../lib/batch'
import { errorText } from '../lib/messages'
import { withViewTransition } from '../lib/motion'
import { RESOLVE_KEY, STORAGE_KEY, TASKS_KEY, upsertTask } from '../lib/tasks'
import { extractBatch, extractSingleUrl } from '../lib/url'
import controls from '../styles/controls.module.css'
import { BatchPreview } from './BatchPreview'
import styles from './Home.module.css'

// - The download page: logo, the input slot, a preview of the resolved file or of a batch,
//   recent tasks.
// - A paste anywhere on the page, outside other fields, goes into the slot; so does a dropped
//   link. Text with one URL fills the input. Text with several becomes a batch of its supported
//   links: with two or more the slot shows their count and the batch preview lists them, with
//   one that link fills the input, and with none the status line names the supported sites.
// - A batch starts its files one by one in paste order; a failure does not stop the rest. When
//   all started, the batch clears; otherwise each row keeps its outcome until the input is
//   cleared.
// - Enter starts only a plain download that is not blocked, or a batch whose every link can
//   start; downloading again and retrying an earlier task need a click. Esc clears the input
//   and the batch, except while a batch is starting.
// - A link dragged over the slot lights it up. While the input is empty, the placeholder names
//   the supported sites and a hint under the slot says where links can go.
// - A preview that can download says where the file goes and that the page can be closed; the
//   toast after a start repeats that the page can be closed.
// - Starting a download and clearing with Esc run in a view transition: the preview fades out
//   and the recent list slides up into its place. A task that arrives while the page is open
//   flashes in the recent list.

const RECENT_COUNT = 5

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

function lampFor(state: ResolveState, plan: Plan | null, noneSupported: boolean, providersFailed: boolean): LampColor {
  if (noneSupported) return 'red'
  if (state.local.kind === 'empty') return 'off'
  if (state.local.kind === 'waiting') return providersFailed ? 'red' : 'amber'
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
  const [noneSupported, setNoneSupported] = useState(false)
  const [batchText, setBatchText] = useState<string | null>(null)
  const [outcomes, setOutcomes] = useState<Map<string, Outcome>>(new Map())
  const [starting, setStarting] = useState(false)
  // - Mirrors `starting` for the page-wide paste listener, which outlives a render.
  const startingRef = useRef(false)
  const [submitError, setSubmitError] = useState<ApiError | null>(null)
  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)

  const providers = useProviders()
  const tasks = useTasks()
  const isNew = useNewIds(tasks.data?.map((task) => task.id))
  const storage = useQuery({ queryKey: STORAGE_KEY, queryFn: api.storage, staleTime: Infinity }).data
  const state = useResolve(input, providers.data, immediate)

  const batch = useMemo(
    () => (batchText !== null && providers.data ? extractBatch(batchText, providers.data) : null),
    [batchText, providers.data],
  )
  // - A batch left with one supported link becomes that link; with none, the status line says so.
  if (batch && batch.links.length < 2) {
    setBatchText(null)
    if (batch.links.length === 1) {
      setInput(batch.links[0].url)
      setImmediate((n) => n + 1)
    } else {
      setNoneSupported(true)
    }
  }
  const inBatch = batchText !== null
  const listed = batch && batch.links.length >= 2 ? batch : null
  const items = useBatch(listed ? listed.links : [])

  const free = storage?.free_bytes ?? state.data?.free_bytes ?? items.find((item) => item.data)?.data?.free_bytes ?? 0
  const planned = state.data ? planFor(state.data, free) : null
  const plan = planned?.plan ?? null
  const view = listed ? batchView(t, items, outcomes, free) : null

  const clear = () => {
    setInput('')
    setNoneSupported(false)
    setBatchText(null)
    setOutcomes(new Map())
    setSubmitError(null)
  }

  const setFromPaste = useCallback((text: string) => {
    if (startingRef.current) return
    const found = extractSingleUrl(text)
    setSubmitError(null)
    setNoneSupported(false)
    setOutcomes(new Map())
    if (found.kind === 'many') {
      setInput('')
      setBatchText(text)
    } else {
      setBatchText(null)
      setInput(found.kind === 'one' ? found.url : text.trim())
      setImmediate((n) => n + 1)
    }
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
      withViewTransition(() => {
        client.setQueryData<Task[]>(TASKS_KEY, (list) => upsertTask(list, task))
        client.removeQueries({ queryKey: RESOLVE_KEY })
        clear()
      })
      toast(t('toast.started', { name: task.file_name ?? t('tasks.unnamed') }), 'success')
      inputRef.current?.focus()
    },
    onError: (err) => setSubmitError(err instanceof ApiError ? err : null),
  })

  const retry = useMutation({
    mutationFn: (id: string) => api.retry(id),
    onSuccess: (task) => {
      client.setQueryData<Task[]>(TASKS_KEY, (list) => upsertTask(list, task))
      client.removeQueries({ queryKey: RESOLVE_KEY })
      navigate(`/tasks?focus=${task.id}`, { viewTransition: true })
    },
    onError: (err) => toast(err instanceof ApiError ? errorText(t, err.error) : t('errors.unknown'), 'error'),
  })

  // - Starts the preview's download, plain or again, unless a request is still running.
  const download = () => {
    if (noneSupported || inBatch || state.local.kind !== 'matched' || state.pending || create.isPending || retry.isPending) return
    if (plan?.kind === 'download') create.mutate({ url: state.local.url, force: plan.force })
  }

  // - Creates the batch's ready files one at a time in paste order and records each outcome.
  const startBatch = async (current: BatchView) => {
    if (!current.canStart || startingRef.current) return
    startingRef.current = true
    setStarting(true)
    const done = new Map<string, Outcome>()
    for (const item of current.ready) {
      try {
        const task = await api.create(item.link.url, false)
        client.setQueryData<Task[]>(TASKS_KEY, (list) => upsertTask(list, task))
        done.set(item.link.key, { kind: 'started' })
      } catch (err) {
        done.set(item.link.key, { kind: 'failed', text: err instanceof ApiError ? errorText(t, err.error) : t('errors.unknown') })
      }
      setOutcomes(new Map(done))
    }
    startingRef.current = false
    setStarting(false)
    const failed = [...done.values()].filter((outcome) => outcome.kind === 'failed').length
    const started = done.size - failed
    if (failed === 0) {
      withViewTransition(() => {
        client.removeQueries({ queryKey: RESOLVE_KEY })
        clear()
      })
      toast(t('toast.batchStarted', { count: started }), 'success')
    } else {
      toast(t('toast.batchPartial', { started, failed }), started > 0 ? 'info' : 'error')
    }
    inputRef.current?.focus()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      if (view) {
        if (view.enterStarts) void startBatch(view)
      } else if (plan?.kind === 'download' && !plan.force) {
        download()
      }
    } else if (event.key === 'Escape' && !starting && (input || noneSupported || inBatch || submitError)) {
      withViewTransition(clear)
    }
  }

  // - Counts nested enter and leave events, so moving across the input inside the slot does
  //   not switch the highlight off. Only a drag that carries text or a link lights it.
  const onDragEnter = (event: DragEvent<HTMLElement>) => {
    const types = Array.from(event.dataTransfer.types)
    if (!types.includes('text/uri-list') && !types.includes('text/plain')) return
    dragDepth.current += 1
    setDragging(true)
  }

  const onDragLeave = () => {
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setDragging(false)
  }

  const onDrop = (event: DragEvent<HTMLElement>) => {
    dragDepth.current = 0
    setDragging(false)
    const uris = event.dataTransfer.getData('text/uri-list')
    const text = uris
      ? uris.split(/\r?\n/).filter((line) => line && !line.startsWith('#')).join('\n')
      : event.dataTransfer.getData('text/plain')
    if (!text) return
    event.preventDefault()
    setFromPaste(text)
  }

  const names = (providers.data ?? []).map((provider) => provider.name)
  const sites = formatList(i18n.language, names, 'conjunction')
  const anySite = formatList(i18n.language, names, 'disjunction')
  const placeholder = names.length > 0 ? t('home.placeholder', { sites: anySite }) : t('home.placeholderPlain')
  const lamp = dragging ? 'amber' : inBatch ? batchLamp(view) : lampFor(state, plan, noneSupported, providers.isError)
  const status = inBatch
    ? batchStatus(t, view, providers.isError)
    : statusLine(t, state, noneSupported, sites, providers.isError)
  const recent = (tasks.data ?? []).slice(0, RECENT_COUNT)

  return (
    <main className={styles.home}>
      <h1 className={styles.logo}>{APP_NAME}</h1>

      <label htmlFor="link" className="visually-hidden">
        {t('home.inputLabel')}
      </label>
      <div className={`${styles.slot} ${dragging ? styles.dragging : ''}`} onDragEnter={onDragEnter}
        onDragLeave={onDragLeave} onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
        <input
          ref={inputRef}
          id="link"
          className={`${styles.input} ${listed && !dragging ? styles.inputBatch : ''}`}
          type="text"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          autoFocus
          placeholder={dragging
            ? t('home.drop')
            : listed ? t('batch.summary', { count: listed.links.length }) : placeholder}
          value={input}
          aria-describedby="link-status link-hint"
          aria-invalid={lamp === 'red' ? true : undefined}
          onChange={(event) => {
            if (starting) return
            setInput(event.target.value)
            setNoneSupported(false)
            setBatchText(null)
            setOutcomes(new Map())
            setSubmitError(null)
          }}
          onPaste={(event) => {
            const text = event.clipboardData.getData('text')
            const found = extractSingleUrl(text)
            if (found.kind === 'none') return
            event.preventDefault()
            if (starting) return
            setFromPaste(text)
          }}
          onKeyDown={onKeyDown}
        />
        <Lamp color={lamp} pulse={lamp === 'amber'} />
        <span className="visually-hidden">{t(`home.lamp.${lampName(lamp)}`)}</span>
      </div>
      <div className={styles.below}>
        <p id="link-status" className={`${styles.status} ${status.error ? styles.statusError : ''}`} aria-live="polite">
          {status.text && <span key={status.text} className={styles.statusText}>{status.text}</span>}
        </p>
        {!input && !inBatch && !status.text && (
          <p id="link-hint" className={styles.hint}>
            {t('home.hint')}
          </p>
        )}
      </div>

      {!noneSupported && !inBatch && state.data && state.local.kind === 'matched' && planned && (
        <Preview
          data={state.data}
          provider={state.local.provider}
          free={free}
          short={planned.short}
          plan={planned.plan}
          locale={i18n.language}
          busy={create.isPending || retry.isPending}
          submitError={submitError}
          onDownload={download}
          onRetry={(id) => retry.mutate(id)}
        />
      )}

      {view && listed && (
        <BatchPreview batch={listed} view={view} free={free} locale={i18n.language} starting={starting}
          onStart={() => void startBatch(view)} />
      )}

      {recent.length > 0 && (
        <section className={styles.recent} aria-labelledby="recent-title">
          <div className={styles.recentHead}>
            <h2 id="recent-title" className={styles.recentTitle}>
              {t('home.recent')}
            </h2>
            <Link to="/tasks" viewTransition>{t('home.viewAll')}</Link>
          </div>
          <ul>
            {recent.map((task) => (
              <li key={task.id}>
                <button type="button" className={`${styles.recentItem} ${isNew(task.id) ? styles.arrived : ''}`}
                  onClick={() => navigate(`/tasks?focus=${task.id}`, { viewTransition: true })}>
                  <span className={styles.recentName}>{task.file_name ?? t('tasks.unnamed')}</span>
                  <span className={styles.recentStatus}>
                    {task.status === 'downloading' && task.size ? (
                      <span className={`${styles.percent} num`}>
                        {formatPercent(i18n.language, Math.min(1, task.bytes_done / task.size))}
                      </span>
                    ) : null}
                    <StatusLamp status={task.status} text={t(`status.${task.status}`)} />
                  </span>
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

// - While the provider list is missing, a URL cannot be judged: "checking" while it loads, the
//   network error once loading failed. The stream's next (re)connect loads it again.
function statusLine(
  t: ReturnType<typeof useTranslation>['t'],
  state: ResolveState,
  noneSupported: boolean,
  sites: string,
  providersFailed: boolean,
): { text: string; error: boolean } {
  if (noneSupported) return { text: t('batch.noneSupported', { sites }), error: true }
  switch (state.local.kind) {
    case 'empty':
      return { text: '', error: false }
    case 'invalid':
      return { text: t('errors.invalid_url'), error: true }
    case 'unsupported':
      return { text: t('home.unsupported', { sites }), error: true }
    case 'waiting':
      return providersFailed ? { text: t('errors.network'), error: true } : { text: t('home.checking'), error: false }
  }
  if (state.error) {
    const error = state.error instanceof ApiError ? state.error.error : null
    return { text: error ? errorText(t, error) : t('errors.unknown'), error: true }
  }
  if (state.pending) return { text: t('home.checking'), error: false }
  return { text: '', error: false }
}

function batchLamp(view: BatchView | null): LampColor {
  if (!view || view.checking > 0) return 'amber'
  if (view.started) return view.rows.some((row) => row.state.kind === 'failed') ? 'red' : 'green'
  return view.canStart ? 'green' : 'red'
}

// - Until the provider list is loaded the batch cannot be read; then the line counts the links
//   checked so far, and once every link is checked it says how many files can start, or that
//   they do not fit. After a start with failures it counts the started and failed files.
function batchStatus(
  t: ReturnType<typeof useTranslation>['t'],
  view: BatchView | null,
  providersFailed: boolean,
): { text: string; error: boolean } {
  if (!view) return providersFailed ? { text: t('errors.network'), error: true } : { text: t('home.checking'), error: false }
  if (view.checking > 0) {
    return { text: t('batch.checking', { done: view.rows.length - view.checking, count: view.rows.length }), error: false }
  }
  if (view.started) {
    const failed = view.rows.filter((row) => row.state.kind === 'failed').length
    const started = view.rows.filter((row) => row.state.kind === 'started').length
    return failed > 0 ? { text: t('batch.outcome', { started, failed }), error: true } : { text: '', error: false }
  }
  if (view.ready.length === 0) return { text: t('batch.noneReady'), error: true }
  if (view.short > 0) return { text: t('batch.noRoom', { count: view.ready.length }), error: true }
  return { text: t('batch.ready', { count: view.ready.length }), error: false }
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

// - While a download is being started, its button keeps its place and shows a spinner;
//   `download` ignores presses until the request ends.
// - Retry is offered only while the file fits in the free space.
// - The key hint names Enter only when Enter downloads; otherwise it names Esc alone.
function Preview({ data, provider, free, short, plan, locale, busy, submitError, onDownload, onRetry }: PreviewProps) {
  const { t } = useTranslation()
  const duplicate = data.duplicate
  const retryable = duplicate != null && (duplicate.status === 'failed' || duplicate.status === 'canceled') && short === 0
  const enterDownloads = plan.kind === 'download' && !plan.force
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
      {plan.kind === 'download' && <p className={styles.promise}>{t('home.promise')}</p>}
      <div className={styles.actions}>
        {plan.kind === 'download' && (
          <button type="button" className={`${controls.button} ${controls.primary}`} onClick={onDownload}
            aria-busy={busy || undefined}>
            {busy && <span className={controls.spinner} aria-hidden="true" />}
            {plan.force ? t('preview.downloadAnyway') : t('preview.download')}
          </button>
        )}
        {retryable && (
          <button type="button" className={controls.button} onClick={() => onRetry(duplicate.task_id)} disabled={busy}>
            {t('preview.retry')}
          </button>
        )}
        {duplicate && (
          <Link className={controls.button} to={`/tasks?focus=${duplicate.task_id}`} viewTransition>
            {t('preview.view')}
          </Link>
        )}
        <span className={styles.keys}>
          <Trans i18nKey={enterDownloads ? 'preview.keys' : 'preview.keysClear'} components={{ key: <kbd /> }} />
        </span>
      </div>
    </section>
  )
}

