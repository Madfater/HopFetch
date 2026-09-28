import { useState, type FormEvent } from 'react'
import { api, type Job } from '../api'

interface Props {
  job: Job
  onSubmit: (answer: string) => Promise<boolean>
}

// - Shows the captcha image the job waits on; `updated_at` busts the cache when a new image arrives.
export default function CaptchaPanel({ job, onSubmit }: Props) {
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const inputId = `captcha-${job.id}`

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!answer.trim() || busy) return
    setBusy(true)
    try {
      await onSubmit(answer.trim())
      setAnswer('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="captcha" onSubmit={submit}>
      <img src={api.captchaUrl(job.id, job.updated_at)} alt="Captcha" width={260} height={100} />
      <div className="captcha-input">
        <label htmlFor={inputId} className="field-label">
          Type the characters in the image
        </label>
        <div className="url-row">
          <input
            id={inputId}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            autoFocus
          />
          <button type="submit" className="primary" disabled={!answer.trim() || busy}>
            Submit
          </button>
        </div>
      </div>
    </form>
  )
}
