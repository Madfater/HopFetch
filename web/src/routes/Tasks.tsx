import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import { ApiError, api } from '../api/client'
import type { Provider, Task } from '../api/types'
import { DeleteDialog } from '../components/DeleteDialog'
import { useNewIds } from '../hooks/useNewIds'
import { useProviders, useTasks } from '../hooks/useTasks'
import { IconButton } from '../components/IconButton'
import { Lamp, StatusLamp } from '../components/Lamp'
import { SegmentedControl } from '../components/SegmentedControl'
import { useToast } from '../components/toast-context'
import { formatBytes, formatDuration, formatPercent, formatSpeed } from '../lib/format'
import { errorText, taskStatusText } from '../lib/messages'
import { FILTERS, matchesFilter, RESOLVE_KEY, removeTask, TASKS_KEY, upsertTask, type Filter } from '../lib/tasks'
import controls from '../styles/controls.module.css'
import styles from './Tasks.module.css'

// - The files page: a status filter that counts its tasks, "clear completed", and a table of
//   every task.
// - `?focus=<id>` scrolls to that task and marks its row for FOCUS_MS; the mark fades when it
//   ends. A task that arrives while the page is open flashes once.
// - Progress bars glide between the progress events, which come at most twice a second.
// - Actions follow the task's state: pause for active resumable tasks, resume for paused ones,
//   cancel for unfinished ones, retry for failed or canceled ones, save for completed ones whose
//   file exists, delete always. Pause, cancel and delete wait while the file is being joined
//   or checked, which the backend refuses.

const FOCUS_MS = 2500
const FINISHING = new Set(['assembling', 'verifying'])

type Action = 'pause' | 'resume' | 'cancel' | 'retry'

export function Tasks() {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [chosenFilter, setFilter] = useState<Filter>('all')
  const [deletingId, setDeletingId] = useState<string | null>(null)

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
  const filter = focused ? 'all' : chosenFilter
  useEffect(() => {
    if (!present) return
    document.getElementById(`task-${focused}`)?.scrollIntoView({ block: 'center' })
    const timer = window.setTimeout(() => setParams({}, { replace: true }), FOCUS_MS)
    return () => window.clearTimeout(timer)
  }, [present, focused, setParams])

  const visible = (all ?? []).filter((task) => matchesFilter(task, filter))
  // - The dialog reads the task from the live list, so a task that completes while it is open
  //   gains the delete-file option.
  const deleting = all?.find((task) => task.id === deletingId) ?? null
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
                if (focused) setParams({}, { replace: true })
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
          <Lamp color={tasks.isError ? 'red' : 'amber'} pulse={!tasks.isError} />
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
              <th scope="col" className={`${styles.colSpeed} ${styles.right}`}>{t('tasks.column.speed')}</th>
              <th scope="col" className={`${styles.colEta} ${styles.right}`}>{t('tasks.column.eta')}</th>
              <th scope="col" className={`${styles.colActions} ${styles.right}`}>{t('tasks.column.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={8}>{t('tasks.emptyFiltered')}</td>
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
                onDelete={() => setDeletingId(task.id)}
              />
            ))}
          </tbody>
        </table>
      )}

      <DeleteDialog
        name={deleting?.file_name ?? t('tasks.unnamed')}
        canDeleteFile={deleting?.status === 'completed' && deleting.file_exists}
        open={deletingId !== null}
        onOpenChange={(open) => !open && setDeletingId(null)}
        onConfirm={(deleteFile) => {
          if (deletingId) remove.mutate({ id: deletingId, deleteFile })
          setDeletingId(null)
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
  onDelete: () => void
}

function TaskRow({ task, provider, focused, arrived, onAction, onDelete }: RowProps) {
  const { t, i18n } = useTranslation()
  const locale = i18n.language
  const name = task.file_name ?? t('tasks.unnamed')
  const ratio = task.size ? Math.min(1, task.bytes_done / task.size) : task.status === 'completed' ? 1 : 0
  const unfinished = task.status === 'queued' || task.status === 'downloading' || task.status === 'paused'
  const finishing = task.phase !== null && FINISHING.has(task.phase)
  const showSpeed = task.status === 'downloading' && task.phase === 'downloading' && task.speed > 0
  const statusText = taskStatusText(t, task)
  const label = (action: string) => t('action.named', { action: t(`action.${action}`), name })

  return (
    <tr id={`task-${task.id}`} className={`${focused ? styles.focused : ''} ${arrived ? styles.arrived : ''}`}>
      <td className={styles.cellStatus}>
        <span className={styles.statusText}>
          <StatusLamp status={task.status} text={statusText} />
        </span>
        {task.notice_key && <span className={styles.sub}>{t(task.notice_key)}</span>}
        {task.status === 'failed' && task.error && (
          <span className={`${styles.sub} ${styles.subError}`}>{errorText(t, task.error)}</span>
        )}
        {task.status === 'completed' && !task.file_exists && (
          <span className={`${styles.sub} ${styles.subError}`}>{t('tasks.fileMissing')}</span>
        )}
        {task.verified === 'corrupt' && <span className={`${styles.sub} ${styles.subError}`}>{t('tasks.videoCorrupt')}</span>}
      </td>
      <td className={styles.cellProvider}>{provider?.name ?? task.provider}</td>
      <td className={`${styles.cellName} ${styles.name}`} title={name}>
        {name}
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
            <div
              className={`${styles.fill} ${task.status === 'downloading' ? styles.fillActive : ''} ${task.status === 'completed' ? styles.fillDone : ''}`}
              style={{ transform: `scaleX(${ratio})` }}
            />
          </div>
          <span className={`${styles.percent} num`}>{formatPercent(locale, ratio)}</span>
        </div>
      </td>
      <td className={`${styles.cellSpeed} ${styles.right} num`}>{showSpeed ? formatSpeed(locale, task.speed) : ''}</td>
      <td className={`${styles.cellEta} ${styles.right} num`}>{showSpeed && task.eta != null ? formatDuration(task.eta) : ''}</td>
      <td className={styles.cellActions}>
        <div className={styles.actions}>
          {(task.status === 'queued' || task.status === 'downloading') && task.resumable && !finishing && (
            <IconButton icon="pause" label={label('pause')} tooltip={t('action.pause')} onClick={() => onAction('pause')} />
          )}
          {task.status === 'paused' && (
            <IconButton icon="resume" label={label('resume')} tooltip={t('action.resume')} onClick={() => onAction('resume')} />
          )}
          {unfinished && !finishing && (
            <IconButton icon="cancel" label={label('cancel')} tooltip={t('action.cancel')} onClick={() => onAction('cancel')} />
          )}
          {(task.status === 'failed' || task.status === 'canceled') && (
            <IconButton icon="retry" label={label('retry')} tooltip={t('action.retry')} onClick={() => onAction('retry')} />
          )}
          {task.status === 'completed' && (
            <IconButton icon="save" label={label('save')} tooltip={task.file_exists ? t('action.save') : t('tasks.fileMissing')}
              href={api.fileUrl(task.id)} disabled={!task.file_exists} />
          )}
          <IconButton icon="delete" label={label('delete')} tooltip={t('action.delete')} onClick={onDelete} disabled={finishing} />
        </div>
      </td>
    </tr>
  )
}
