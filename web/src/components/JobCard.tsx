import { api, type Job, type JobState } from '../api'
import { formatBytes, formatDuration, formatSpeed } from '../format'
import CaptchaPanel from './CaptchaPanel'

interface Props {
  job: Job
  providerLabel: string
  act: (action: () => Promise<unknown>, success?: string) => Promise<boolean>
}

const STATE_LABELS: Record<JobState, string> = {
  queued: 'Queued',
  resolving: 'Resolving',
  preparing: 'Preparing',
  solving_captcha: 'Solving captcha',
  awaiting_captcha: 'Needs captcha',
  waiting: 'Waiting',
  generating_links: 'Getting links',
  downloading: 'Downloading',
  assembling: 'Joining parts',
  verifying: 'Verifying',
  completed: 'Completed',
  failed: 'Failed',
  paused: 'Paused',
}

const RESTING: JobState[] = ['completed', 'failed', 'paused']

function tone(state: JobState): string {
  if (state === 'completed') return 'ok'
  if (state === 'failed') return 'bad'
  if (state === 'awaiting_captcha') return 'warn'
  if (state === 'paused') return 'idle'
  return 'busy'
}

// - One download: name, state badge, progress, stats and the actions its state allows.
export default function JobCard({ job, providerLabel, act }: Props) {
  const running = !RESTING.includes(job.state)
  const percent = job.size ? Math.min(100, (job.done_bytes / job.size) * 100) : 0
  const eta = job.speed > 0 && job.size ? (job.size - job.done_bytes) / job.speed : NaN
  const title = job.filename ?? job.url

  function remove() {
    const note = job.state === 'completed' ? ' The downloaded file stays on disk.' : ' Downloaded parts are deleted.'
    if (window.confirm(`Remove "${title}" from the list?${note}`)) {
      act(() => api.remove(job.id), 'Download removed')
    }
  }

  return (
    <li className="card job" data-state={job.state}>
      <div className="job-head">
        <div className="job-title">
          <h3 title={title}>{title}</h3>
          <p className="muted small">
            <span className="chip">{providerLabel}</span>
            {job.size != null && <span>{formatBytes(job.size)}</span>}
          </p>
        </div>
        <span className={`badge badge-${tone(job.state)}`}>{STATE_LABELS[job.state]}</span>
      </div>

      <div
        className="progress"
        role="progressbar"
        aria-label={`Progress of ${title}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
      >
        <div className={`progress-fill ${running ? 'progress-live' : ''}`} style={{ width: `${percent}%` }} />
      </div>

      <div className="stats small">
        <span>
          {formatBytes(job.done_bytes)} of {formatBytes(job.size)} ({percent.toFixed(1)}%)
        </span>
        {job.state === 'downloading' && (
          <>
            <span>{formatSpeed(job.speed)}</span>
            <span>ETA {formatDuration(eta)}</span>
            <span>
              {job.active_connections}/{job.links_count} connections
            </span>
          </>
        )}
        {job.parts_total > 0 && (
          <span>
            Parts {job.parts_done}/{job.parts_total}
          </span>
        )}
      </div>

      {job.message && (
        <p className={`message small ${job.state === 'failed' ? 'message-error' : ''}`}>{job.message}</p>
      )}
      {job.verified === 'corrupt' && (
        <p className="message small message-error">ffmpeg reported problems in this video.</p>
      )}

      {job.state === 'awaiting_captcha' && (
        <CaptchaPanel job={job} onSubmit={(answer) => act(() => api.captcha(job.id, answer))} />
      )}

      <div className="actions">
        {job.state === 'completed' && (
          <a className="button primary" href={api.fileUrl(job.id)} download>
            Save file
          </a>
        )}
        {running && (
          <button type="button" onClick={() => act(() => api.pause(job.id))}>
            Pause
          </button>
        )}
        {(job.state === 'paused' || job.state === 'failed') && (
          <button type="button" className="primary" onClick={() => act(() => api.resume(job.id))}>
            Resume
          </button>
        )}
        <button type="button" className="danger" onClick={remove}>
          Remove
        </button>
      </div>
    </li>
  )
}
