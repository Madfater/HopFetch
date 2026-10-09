import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import { ApiError, api } from '../api/client'
import type { Provider, Task } from '../api/types'
import { ConfirmDialog, type ConfirmKind } from '../components/ConfirmDialog'
import { useNewIds } from '../hooks/useNewIds'
import { useProviders, useTasks } from '../hooks/useTasks'
import { IconButton } from '../components/IconButton'
import { Lamp, StatusLamp } from '../components/Lamp'
import { SegmentedControl } from '../components/SegmentedControl'
import { useToast } from '../components/toast-context'
import { formatBytes, formatDuration, formatPercent, formatSpeed } from '../lib/format'
import { errorText, taskStatus } from '../lib/messages'
import { FILTERS, matchesFilter, parseFilter, RESOLVE_KEY, removeTask, TASKS_KEY, upsertTask, type Filter } from '../lib/tasks'
import controls from '../styles/controls.module.css'
import styles from './Tasks.module.css'

// - The files page: a status filter that counts its tasks, "clear completed", and a table of
//   every task.
// - `?focus=<id>` scrolls to that task and marks its row for FOCUS_MS; the mark fades when it
//   ends. A task that arrives while the page is open flashes once.
// - `?filter=<filter>` opens the page on that filter; choosing another filter drops it.
// - A row's status cell holds the state and its step; the task's notes, such as an error or a
//   restart notice, sit under the file name, and speed and time left sit under the progress bar
//   while the task downloads.
// - Progress bars glide between the progress events, which come at most twice a second.
// - Actions follow the task's state: pause for active resumable tasks, resume for paused ones,
//   cancel for unfinished ones, retry for failed or canceled ones, save for completed ones whose
//   file exists, delete always. Pause, cancel and delete wait while the file is being joined
//   or checked, which the backend refuses.
// - Cancel and delete open a confirm dialog first; it states the downloaded bytes the action
//   throws away, which is every byte of a task that is not completed.

const FOCUS_MS = 2500
const FINISHING = new Set(['assembling', 'verifying'])

// - The progress fill's color by status: active teal while downloading, a quiet done green when
//   completed, failed red when failed; other statuses keep the neutral muted fill.
// - An empty fill is hidden, so its edge never shows at the left end of a 0% track.
const FILL: Partial<Record<Task['status'], string>> = {
  downloading: styles.fillActive,
  completed: styles.fillDone,
  failed: styles.fillFailed,
}

type Action = 'pause' | 'resume' | 'cancel' | 'retry'

interface Confirming {
  id: string
  kind: ConfirmKind
}

export function Tasks() {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [chosenFilter, setFilter] = useState<Filter>('all')
  const [confirming, setConfirming] = useState<Confirming | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const tasks = useTasks()
  const providers = useProviders()
  const providerById = new Map((providers.data ?? []).map((p) => [p.id, p]))

  const fail = (err: unknown) => toast(err instanceof ApiError ? errorText(t, err.error) : t('errors.unknown'), 'error')

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: Action }) => api[action](id),
    onSuccess: (task) => {
      client.setQueryData<Task[]>(TASKS_KEY, (list) => upsertTask(list, task))
      client.removeQueries({ queryKey: RESOLVE_KEY })
    },
    onError: fail,
  })

  const remove = useMutation({
    mutationFn: ({ id, deleteFile }: { id: string; deleteFile: boolean }) => api.remove(id, deleteFile),
    onSuccess: (_, { id }) => {
      client.setQueryData<Task[]>(TASKS_KEY, (list) => removeTask(list, id))
      client.removeQueries({ queryKey: RESOLVE_KEY })
      toast(t('toast.removed'))
    },
    onError: fail,
  })

  const clear = useMutation({
    mutationFn: api.clearCompleted,
    onSuccess: ({ removed }) => {
      client.setQueryData<Task[]>(TASKS_KEY, (list) => list?.filter((task) => task.status !== 'completed'))
      client.removeQueries({ queryKey: RESOLVE_KEY })
      toast(t('toast.cleared', { count: removed }))
    },
    onError: fail,
  })

  // - While `?focus` is set the filter shows every task, so the focused row is visible; the
  //   parameter is dropped after FOCUS_MS, which ends the mark.
  const focused = params.get('focus')
  const all = tasks.data
  const present = focused !== null && (all?.some((task) => task.id === focused) ?? false)
  const filter = focused ? 'all' : (parseFilter(params.get('filter')) ?? chosenFilter)
  useEffect(() => {
    if (!present) return
    document.getElementById(`task-${focused}`)?.scrollIntoView({ block: 'center' })
    const timer = window.setTimeout(() => setParams({}, { replace: true }), FOCUS_MS)
    return () => window.clearTimeout(timer)
  }, [present, focused, setParams])

  const visible = (all ?? []).filter((task) => matchesFilter(task, filter))
  // - The dialog reads the task from the live list, so a task that completes while it is open
  //   gains the delete-file option and loses the cost line, and the cost line follows progress.
  // - `confirming` outlives the open state, so the closing dialog keeps its words.
  const target = all?.find((task) => task.id === confirming?.id) ?? null
  const hasCompleted = (all ?? []).some((task) => task.status === 'completed')
  const isNew = useNewIds(all?.map((task) => task.id))

  return (
    <main className="page">
      <div className={styles.head}>
        <h1 className="page-title">{t('tasks.title')}</h1>
        {all && all.length > 0 && (
          <div className={styles.toolbar}>
            <SegmentedControl label={t('tasks.filter.label')} value={filter}
              onChange={(value) => {
                setFilter(value)
                if (focused || params.has('filter')) setParams({}, { replace: true })
              }}
              options={FILTERS.map((value) => ({
                value,
                label: (
                  <span>
                    {t(`tasks.filter.${value}`)}{' '}
                    <span className={`${styles.count} num`}>{all.filter((task) => matchesFilter(task, value)).length}</span>
                  </span>
                ),
              }))} />
            <button type="button" className={controls.button} disabled={!hasCompleted || clear.isPending}
              onClick={() => clear.mutate()}>
              {t('tasks.clearCompleted')}
            </button>
          </div>
        )}
      </div>

      {!all ? (
        <p className={styles.state}>
          <Lamp color={tasks.isError ? 'failed' : 'active'} pulse={!tasks.isError} />
          {tasks.isError ? t('errors.network') : t('tasks.loading')}
        </p>
      ) : all.length === 0 ? (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>{t('tasks.empty')}</p>
          <Link className={controls.button} to="/" viewTransition>{t('tasks.emptyLink')}</Link>
        </div>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col" className={styles.colStatus}>{t('tasks.column.status')}</th>
              <th scope="col" className={styles.colProvider}>{t('tasks.column.provider')}</th>
              <th scope="col">{t('tasks.column.name')}</th>
              <th scope="col" className={`${styles.colSize} ${styles.right}`}>{t('tasks.column.size')}</th>
              <th scope="col" className={styles.colProgress}>{t('tasks.column.progress')}</th>
              <th scope="col" className={`${styles.colActions} ${styles.right}`}>{t('tasks.column.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={6}>{t('tasks.emptyFiltered')}</td>
              </tr>
            )}
            {visible.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                provider={providerById.get(task.provider)}
                focused={focused === task.id}
                arrived={isNew(task.id)}
                onAction={(action) => act.mutate({ id: task.id, action })}
                onConfirm={(kind) => {
                  setConfirming({ id: task.id, kind })
                  setConfirmOpen(true)
                }}
              />
            ))}
          </tbody>
        </table>
      )}

      <ConfirmDialog
        kind={confirming?.kind ?? 'delete'}
        name={target?.file_name ?? t('tasks.unnamed')}
        discards={target && target.status !== 'completed' ? target.bytes_done : 0}
        canDeleteFile={target?.status === 'completed' && target.file_exists}
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onConfirm={(deleteFile) => {
          if (confirming?.kind === 'cancel') act.mutate({ id: confirming.id, action: 'cancel' })
          else if (confirming) remove.mutate({ id: confirming.id, deleteFile })
          setConfirmOpen(false)
        }}
      />
    </main>
  )
}

interface RowProps {
  task: Task
  provider: Provider | undefined
  focused: boolean
  arrived: boolean
  onAction: (action: Action) => void
  onConfirm: (kind: ConfirmKind) => void
}

function TaskRow({ task, provider, focused, arrived, onAction, onConfirm }: RowProps) {
  const { t, i18n } = useTranslation()
  const locale = i18n.language
  const name = task.file_name ?? t('tasks.unnamed')
  const ratio = task.size ? Math.min(1, task.bytes_done / task.size) : task.status === 'completed' ? 1 : 0
  const unfinished = task.status === 'queued' || task.status === 'downloading' || task.status === 'paused'
  const finishing = task.phase !== null && FINISHING.has(task.phase)
  const showSpeed = task.status === 'downloading' && task.phase === 'downloading' && task.speed > 0
  const status = taskStatus(t, task)
  const label = (action: string) => t('action.named', { action: t(`action.${action}`), name })

  return (
    <tr id={`task-${task.id}`} className={`${focused ? styles.focused : ''} ${arrived ? styles.arrived : ''}`}>
      <td className={styles.cellStatus}>
        <span className={styles.statusText}>
          <StatusLamp status={task.status} text={status.text} />
        </span>
        {status.detail && <span className={styles.sub}>{status.detail}</span>}
      </td>
      <td className={styles.cellProvider}>{provider?.name ?? task.provider}</td>
      <td className={styles.cellName}>
        <span className={styles.name} title={name}>{name}</span>
        {task.notice_key && <span className={styles.sub}>{t(task.notice_key)}</span>}
        {task.status === 'failed' && task.error && (
          <span className={`${styles.sub} ${styles.subError}`}>{errorText(t, task.error)}</span>
        )}
        {task.status === 'completed' && !task.file_exists && (
          <span className={`${styles.sub} ${styles.subError}`}>{t('tasks.fileMissing')}</span>
        )}
        {task.verified === 'corrupt' && <span className={`${styles.sub} ${styles.subError}`}>{t('tasks.videoCorrupt')}</span>}
      </td>
      <td className={`${styles.cellSize} ${styles.right} num`}>{formatBytes(locale, task.size)}</td>
      <td className={styles.cellProgress}>
        <div className={styles.progress}>
          <div
            className={styles.track}
            role="progressbar"
            aria-label={t('tasks.progressLabel', { name })}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(ratio * 100)}
          >
            <div className={`${styles.fill} ${FILL[task.status] ?? ''}`} style={{ transform: `translateX(${(ratio - 1) * 100}%)`, visibility: ratio > 0 ? undefined : 'hidden' }} />
          </div>
          <span className={`${styles.percent} num`}>{formatPercent(locale, ratio)}</span>
        </div>
        {showSpeed && (
          <span className={`${styles.sub} ${styles.rate} num`}>
            {task.eta != null
              ? t('tasks.rate', { speed: formatSpeed(locale, task.speed), eta: formatDuration(task.eta) })
              : formatSpeed(locale, task.speed)}
          </span>
        )}
      </td>
      <td className={styles.cellActions}>
        <div className={styles.actions}>
          {(task.status === 'queued' || task.status === 'downloading') && task.resumable && !finishing && (
            <IconButton icon="pause" label={label('pause')} tooltip={t('action.pause')} onClick={() => onAction('pause')} />
          )}
          {task.status === 'paused' && (
            <IconButton icon="resume" label={label('resume')} tooltip={t('action.resume')} onClick={() => onAction('resume')} />
          )}
          {unfinished && !finishing && (
            <IconButton icon="cancel" label={label('cancel')} tooltip={t('action.cancel')} onClick={() => onConfirm('cancel')} />
          )}
          {(task.status === 'failed' || task.status === 'canceled') && (
            <IconButton icon="retry" label={label('retry')} tooltip={t('action.retry')} onClick={() => onAction('retry')} />
          )}
          {task.status === 'completed' && (
            <IconButton icon="save" label={label('save')} tooltip={task.file_exists ? t('action.save') : t('tasks.fileMissing')}
              href={api.fileUrl(task.id)} disabled={!task.file_exists} />
          )}
          <IconButton icon="delete" label={label('delete')} tooltip={t('action.delete')} onClick={() => onConfirm('delete')}
            disabled={finishing} />
        </div>
      </td>
    </tr>
  )
}
