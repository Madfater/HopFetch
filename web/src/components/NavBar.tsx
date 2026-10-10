import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router'
import { api } from '../api/client'
import { useTasks } from '../hooks/useTasks'
import { formatStorage } from '../lib/format'
import { isActive, needsAttention, STORAGE_KEY } from '../lib/tasks'
import { Lamp } from './Lamp'
import styles from './NavBar.module.css'

// - Sticky top bar: the three pages, and NAS free space on the right.
// - The Downloads tab counts queued and downloading tasks, and beside that, behind a red lamp,
//   the failed tasks that wait on the user.
// - The active tab's underline has a view-transition name, so a page change slides it to the
//   new tab.
// - Free space is read once and then kept current by `storage` events. On a narrow screen the
//   amount sits over a one-word caption, such as "free", so the tabs and the amount fit on one
//   line.
// - Until the first answer arrives, a dim placeholder stands in for the amount and screen readers
//   hear that the free space is being checked; only a failed request says it is unknown.
// - While the event stream is down, a line under the bar says the app is reconnecting.
// - Each count a screen reader hears in the Downloads tab is set off by a hidden separator, so
//   the tab's name reads as a list rather than one run-on phrase.

const TABS = [
  { to: '/', key: 'nav.home', end: true, counted: false },
  { to: '/tasks', key: 'nav.tasks', end: false, counted: true },
  { to: '/settings', key: 'nav.settings', end: false, counted: false },
]

export function NavBar({ connected }: { connected: boolean }) {
  const { t, i18n } = useTranslation()
  const storage = useQuery({ queryKey: STORAGE_KEY, queryFn: api.storage, staleTime: Infinity })
  const tasks = useTasks().data
  const active = tasks ? tasks.filter(isActive).length : null
  const failed = tasks ? tasks.filter(needsAttention).length : 0

  return (
    <header className={styles.header}>
      <div className={styles.bar}>
        <div className={styles.inner}>
          <nav aria-label={t('nav.label')} className={styles.tabs}>
            {TABS.map((tab) => (
              <NavLink key={tab.to} to={tab.to} end={tab.end} viewTransition
                className={({ isActive: current }) => `${styles.tab} ${current ? styles.current : ''}`}>
                {({ isActive: current }) => (
                  <>
                    {t(tab.key)}
                    {tab.counted && <Count value={active} label={t('nav.active', { count: active ?? 0 })} />}
                    {tab.counted && failed > 0 && (
                      <>
                        <span className={styles.attention} aria-hidden="true">
                          <Lamp color="failed" />
                          <span className="num">{failed}</span>
                        </span>
                        <span className="visually-hidden">{t('a11y.separator')}</span>
                        <span className="visually-hidden">{t('nav.attention', { count: failed })}</span>
                      </>
                    )}
                    {current && <span className={styles.indicator} aria-hidden="true" />}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
          <p className={styles.storage}>
            {storage.data || storage.isPending ? (
              <Storage amount={storage.data ? formatStorage(i18n.language, storage.data.free_bytes) : null} />
            ) : (
              t('nav.storageUnknown')
            )}
          </p>
        </div>
      </div>
      {!connected && (
        <div className={styles.offline}>
          <p className={styles.offlineText} role="status">
            <Lamp color="failed" />
            {t('toast.offline')}
          </p>
        </div>
      )}
    </header>
  )
}

// - The free space in its long and short forms; CSS shows one of them. A null `amount` is still
//   loading: both forms keep their words around a placeholder, hidden from screen readers.
function Storage({ amount }: { amount: string | null }) {
  const { t } = useTranslation()
  const value = <span className={amount ? 'num' : styles.pending}>{amount ?? '00 GB'}</span>
  return (
    <>
      <span aria-hidden={amount ? undefined : true}>
        <span className={styles.storageLong}>{t('nav.storage')} {value}</span>
        <span className={styles.storageShort}>
          {value}
          <span className={styles.caption}>{t('nav.storageShort')}</span>
        </span>
      </span>
      {!amount && <span className="visually-hidden">{t('nav.storageLoading')}</span>}
    </>
  )
}

// - The count badge, hidden at zero. `value` is null until the task list has loaded, so the
//   first count shows without a pop; later changes pop it.
function Count({ value, label }: { value: number | null; label: string }) {
  const { t } = useTranslation()
  const [shown, setShown] = useState(value)
  const [pops, setPops] = useState(0)
  if (value !== shown) {
    setShown(value)
    if (shown !== null && value !== null) setPops((n) => n + 1)
  }
  if (!value) return null
  return (
    <>
      <span key={pops} className={`${styles.count} ${pops > 0 ? styles.pop : ''} num`} aria-hidden="true">
        {value}
      </span>
      <span className="visually-hidden">{t('a11y.separator')}</span>
      <span className="visually-hidden">{label}</span>
    </>
  )
}
