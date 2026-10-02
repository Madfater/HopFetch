import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Checkbox } from 'radix-ui'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, api } from '../api/client'
import type { Settings as SettingsData } from '../api/types'
import { useToast } from '../components/toast-context'
import { chooseLanguage, LANGUAGES, toSupported, type Language } from '../i18n'
import { errorText } from '../lib/messages'
import controls from '../styles/controls.module.css'
import styles from './Settings.module.css'

// - Server settings shared by every user (connections, part size, public proxies, simultaneous
//   downloads), the read-only download folder, and this browser's language.
// - The part size is edited in MiB and sent in bytes.

const MIB = 2 ** 20

interface Draft {
  connections: string
  splitMib: string
  useProxies: boolean
  maxActive: string
}

function toDraft(settings: SettingsData): Draft {
  return {
    connections: String(settings.connections),
    splitMib: String(Math.round(settings.split_size / MIB)),
    useProxies: settings.use_proxies,
    maxActive: String(settings.max_active_jobs),
  }
}

export function Settings() {
  const { t, i18n } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [edits, setEdits] = useState<Draft | null>(null)
  const [error, setError] = useState<string | null>(null)
  const draft = edits ?? (settings.data ? toDraft(settings.data) : null)

  const save = useMutation({
    mutationFn: (value: Draft) =>
      api.saveSettings({
        connections: Number(value.connections),
        split_size: Math.round(Number(value.splitMib) * MIB),
        use_proxies: value.useProxies,
        max_active_jobs: Number(value.maxActive),
      }),
    onSuccess: (saved) => {
      client.setQueryData(['settings'], saved)
      setEdits(null)
      setError(null)
      toast(t('settings.saved'), 'success')
    },
    onError: (err) => setError(err instanceof ApiError ? errorText(t, err.error) : t('errors.unknown')),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (draft) save.mutate(draft)
  }

  const update = (change: Partial<Draft>) => {
    if (draft) setEdits({ ...draft, ...change })
  }

  return (
    <main className={`page ${styles.settings}`}>
      <h1 className={styles.title}>{t('settings.title')}</h1>

      {!draft || !settings.data ? (
        <p className={controls.hint}>{settings.isError ? t('errors.network') : t('settings.loading')}</p>
      ) : (
        <form className={styles.section} onSubmit={submit} noValidate>
          <h2 className={styles.sectionTitle}>{t('settings.shared')}</h2>
          <p className={controls.hint}>{t('settings.sharedHint')}</p>

          <NumberField id="connections" label={t('settings.connections')} hint={t('settings.connectionsHint')}
            min={1} max={64} value={draft.connections} onChange={(value) => update({ connections: value })} />
          <NumberField id="split" label={t('settings.splitSize')} hint={t('settings.splitSizeHint')}
            min={20} value={draft.splitMib} onChange={(value) => update({ splitMib: value })} />
          <NumberField id="active" label={t('settings.maxActive')} hint={t('settings.maxActiveHint')}
            min={1} max={10} value={draft.maxActive} onChange={(value) => update({ maxActive: value })} />

          <label className={styles.check}>
            <Checkbox.Root className={styles.box} checked={draft.useProxies} aria-describedby="proxies-hint"
              onCheckedChange={(value) => update({ useProxies: value === true })}>
              <Checkbox.Indicator>
                <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor"
                  strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2.5 6.2 5 8.5l4.5-5" />
                </svg>
              </Checkbox.Indicator>
            </Checkbox.Root>
            <span className={controls.field}>
              <span className={controls.label}>{t('settings.useProxies')}</span>
              <span id="proxies-hint" className={controls.hint}>{t('settings.useProxiesHint')}</span>
            </span>
          </label>

          <div className={controls.field}>
            <span className={controls.label}>{t('settings.root')}</span>
            <span className={`${styles.root} num`}>{settings.data.download_root}</span>
            <span className={controls.hint}>{t('settings.rootHint')}</span>
          </div>

          <div className={styles.actions}>
            <button type="submit" className={controls.button} disabled={save.isPending}>
              {t('settings.save')}
            </button>
            {error && (
              <p className={controls.error} role="alert">
                {error}
              </p>
            )}
          </div>
        </form>
      )}

      <section className={styles.section} aria-labelledby="browser-title">
        <h2 id="browser-title" className={styles.sectionTitle}>{t('settings.browser')}</h2>
        <div className={controls.field}>
          <label htmlFor="language" className={controls.label}>{t('settings.language')}</label>
          <select id="language" className={`${controls.input} ${styles.select}`} aria-describedby="language-hint"
            value={toSupported(i18n.language)} onChange={(event) => chooseLanguage(event.target.value as Language)}>
            {LANGUAGES.map((language) => (
              <option key={language} value={language} lang={language}>
                {t(`language.${language}`)}
              </option>
            ))}
          </select>
          <span id="language-hint" className={controls.hint}>{t('settings.languageHint')}</span>
        </div>
      </section>
    </main>
  )
}

interface NumberFieldProps {
  id: string
  label: string
  hint: string
  min: number
  max?: number
  value: string
  onChange: (value: string) => void
}

function NumberField({ id, label, hint, min, max, value, onChange }: NumberFieldProps) {
  return (
    <div className={controls.field}>
      <label htmlFor={id} className={controls.label}>{label}</label>
      <input id={id} className={`${controls.input} ${styles.number} num`} type="number" inputMode="numeric"
        min={min} max={max} step={1} value={value} aria-describedby={`${id}-hint`}
        onChange={(event) => onChange(event.target.value)} />
      <span id={`${id}-hint`} className={controls.hint}>{hint}</span>
    </div>
  )
}
