import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Job, type Provider } from './api'
import AddForm from './components/AddForm'
import JobCard from './components/JobCard'
import Toasts, { type Toast } from './components/Toasts'

const POLL_MS = 1000

// - Polls the job list every second while the tab is visible.
// - Shows a banner when the backend cannot be reached, and clears it on the next good poll.
export default function App() {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [providers, setProviders] = useState<Provider[]>([])
  const [offline, setOffline] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextToast = useRef(1)

  const notify = useCallback((text: string, kind: Toast['kind'] = 'error') => {
    const id = nextToast.current++
    setToasts((all) => [...all, { id, text, kind }])
    window.setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), 5000)
  }, [])

  const refresh = useCallback(async () => {
    try {
      setJobs(await api.jobs())
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  useEffect(() => {
    api.providers().then(setProviders).catch(() => setOffline(true))
    refresh()
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') refresh()
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [refresh])

  const act = useCallback(
    async (action: () => Promise<unknown>, success?: string): Promise<boolean> => {
      try {
        await action()
        if (success) notify(success, 'info')
        return true
      } catch (err) {
        notify(err instanceof Error ? err.message : String(err))
        return false
      } finally {
        refresh()
      }
    },
    [notify, refresh],
  )

  const labels = Object.fromEntries(providers.map((p) => [p.name, p.label]))

  return (
    <div className="page">
      <header className="header">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <h1>Downloader</h1>
        </div>
        <p className="supported">
          {providers.length > 0 && <>Supports {providers.map((p) => p.label).join(', ')}</>}
        </p>
      </header>

      {offline && (
        <div className="banner" role="alert">
          Cannot reach the server. Retrying...
        </div>
      )}

      <AddForm onCreate={(job) => act(() => api.create(job), 'Download added')} />

      <section className="jobs" aria-label="Downloads">
        <h2>Downloads</h2>
        {jobs === null ? (
          <p className="muted">Loading...</p>
        ) : jobs.length === 0 ? (
          <div className="empty">
            <p className="empty-title">No downloads yet</p>
            <p className="muted">Paste a file link above to start one.</p>
          </div>
        ) : (
          <ul className="job-list">
            {jobs.map((job) => (
              <JobCard key={job.id} job={job} providerLabel={labels[job.provider] ?? job.provider} act={act} />
            ))}
          </ul>
        )}
      </section>

      <Toasts toasts={toasts} />
    </div>
  )
}
