import { useEffect, useState, type FormEvent } from 'react'
import { api, type NewJob, type Resolved } from '../api'

interface Props {
  onCreate: (job: NewJob) => Promise<boolean>
}

// - Resolves the URL against the backend as the user types, showing which provider will handle it.
// - Filename, connections and split size sit in a collapsible options panel.
export default function AddForm({ onCreate }: Props) {
  const [url, setUrl] = useState('')
  const [filename, setFilename] = useState('')
  const [connections, setConnections] = useState(20)
  const [splitSize, setSplitSize] = useState('20MB')
  const [resolved, setResolved] = useState<Resolved | null>(null)
  const [urlError, setUrlError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const value = url.trim()
    if (!value) {
      setResolved(null)
      setUrlError(null)
      return
    }
    let stale = false
    const timer = window.setTimeout(() => {
      api
        .resolve(value)
        .then((r) => !stale && (setResolved(r), setUrlError(null)))
        .catch((err: Error) => !stale && (setResolved(null), setUrlError(err.message)))
    }, 250)
    return () => {
      stale = true
      window.clearTimeout(timer)
    }
  }, [url])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!url.trim() || busy) return
    setBusy(true)
    try {
      const created = await onCreate({
        url: url.trim(),
        filename: filename.trim() || undefined,
        connections,
        split_size: splitSize,
      })
      if (created) {
        setUrl('')
        setFilename('')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card add-form" onSubmit={submit} noValidate>
      <label htmlFor="url" className="field-label">
        File link
      </label>
      <div className="url-row">
        <input
          id="url"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="https://k2s.cc/file/..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          aria-invalid={urlError ? true : undefined}
          aria-describedby="url-hint"
        />
        <button type="submit" className="primary" disabled={!url.trim() || busy}>
          {busy ? 'Adding...' : 'Download'}
        </button>
      </div>
      <p id="url-hint" className={`hint ${urlError ? 'hint-error' : ''}`} aria-live="polite">
        {urlError ?? (resolved ? <>Handled by <strong>{resolved.label}</strong></> : ' ')}
      </p>

      <details className="options">
        <summary>Options</summary>
        <div className="option-grid">
          <label>
            <span className="field-label">Save as</span>
            <input
              type="text"
              placeholder="Name from the platform"
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
            />
          </label>
          <label>
            <span className="field-label">Connections</span>
            <input
              type="number"
              min={1}
              max={64}
              value={connections}
              onChange={(e) => setConnections(Number(e.target.value))}
            />
          </label>
          <label>
            <span className="field-label">Part size</span>
            <input type="text" value={splitSize} onChange={(e) => setSplitSize(e.target.value)} />
          </label>
        </div>
      </details>
    </form>
  )
}
