import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router'
import { api } from '../api/client'
import { formatStorage } from '../lib/format'
import { STORAGE_KEY } from '../lib/tasks'
import styles from './NavBar.module.css'

// - Top bar: the three pages on the left, NAS free space on the right.
// - Free space is read once and then kept current by `storage` events.
// - While the event stream is down, a line under the bar says the app is reconnecting.

const TABS = [
  { to: '/', key: 'nav.home', end: true },
  { to: '/tasks', key: 'nav.tasks', end: false },
  { to: '/settings', key: 'nav.settings', end: false },
]

export function NavBar({ connected }: { connected: boolean }) {
  const { t, i18n } = useTranslation()
  const storage = useQuery({ queryKey: STORAGE_KEY, queryFn: api.storage, staleTime: Infinity })

  return (
    <header>
      <div className={styles.bar}>
        <div className={styles.inner}>
          <nav aria-label={t('nav.label')} className={styles.tabs}>
            {TABS.map((tab) => (
              <NavLink key={tab.to} to={tab.to} end={tab.end}
                className={({ isActive }) => `${styles.tab} ${isActive ? styles.active : ''}`}>
                {t(tab.key)}
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
        <p className={styles.offline} role="status">
          {t('toast.offline')}
        </p>
      )}
    </header>
  )
}
