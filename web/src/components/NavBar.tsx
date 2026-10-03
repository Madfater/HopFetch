import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router'
import { api } from '../api/client'
import { useTasks } from '../hooks/useTasks'
import { formatStorage } from '../lib/format'
import { isActive, STORAGE_KEY } from '../lib/tasks'
import { Lamp } from './Lamp'
import styles from './NavBar.module.css'

// - Sticky top bar: the three pages, and NAS free space on the right.
// - The Files tab counts queued and downloading tasks.
// - The active tab's underline has a view-transition name, so a page change slides it to the
//   new tab.
// - Free space is read once and then kept current by `storage` events.
// - While the event stream is down, a line under the bar says the app is reconnecting.

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
                    {current && <span className={styles.indicator} aria-hidden="true" />}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
          <p className={styles.storage}>
            {storage.data ? (
              <span>
                {t('nav.storage')}{' '}
                <span className="num">{formatStorage(i18n.language, storage.data.free_bytes)}</span>
              </span>
            ) : (
              t('nav.storageUnknown')
            )}
          </p>
        </div>
      </div>
      {!connected && (
        <div className={styles.offline}>
          <p className={styles.offlineText} role="status">
            <Lamp color="red" />
            {t('toast.offline')}
          </p>
        </div>
      )}
    </header>
  )
}

// - The count badge, hidden at zero. `value` is null until the task list has loaded, so the
//   first count shows without a pop; later changes pop it.
function Count({ value, label }: { value: number | null; label: string }) {
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
      <span className="visually-hidden">{label}</span>
    </>
  )
}
