import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, api } from '../api/client'
import { Lamp } from '../components/Lamp'
import { NumberStepper } from '../components/NumberStepper'
import { SegmentedControl } from '../components/SegmentedControl'
import { Switch } from '../components/Switch'
import { chooseLanguage, LANGUAGES, toSupported } from '../i18n'
import { formatStorage } from '../lib/format'
import { errorText } from '../lib/messages'
import {
  changedFields, LIMITS, NUMBER_FIELDS, parseWhole, stepValue, toChange, toDraft, validate, type Draft, type NumberField,
} from '../lib/settings'
import { STORAGE_KEY } from '../lib/tasks'
import controls from '../styles/controls.module.css'
import styles from './Settings.module.css'

// - Three plates: the download settings, stored on the server and shared by everyone; the
//   download folder and its free space, read only; and other settings, which hold the language.
// - The download settings are a draft until saved. The footer counts unsaved changes and
//   offers Discard and Save, which becomes the primary button only when there is something to
//   save; while there is, the footer stays in view. After a save it reads "Settings saved" for
//   SAVED_MS.
// - A number field shows its problem once it has lost focus or a save was tried. A save with a
//   problem sends nothing and focuses the first field in trouble.
// - One save runs at a time. An edit made while it runs is kept as the new draft, with any
//   problem it shows; editing only clears the message of a save that already failed.
// - The language applies at once and is kept in this browser only.

const SAVED_MS = 2500

const NUMBER_ROWS: { field: NumberField; id: string; label: string; hint: string; unit?: string }[] = [
  { field: 'connections', id: 'connections', label: 'settings.connections', hint: 'settings.connectionsHint' },
  { field: 'maxActive', id: 'max-active', label: 'settings.maxActive', hint: 'settings.maxActiveHint' },
  { field: 'splitMib', id: 'split-size', label: 'settings.splitSize', hint: 'settings.splitSizeHint', unit: 'settings.mib' },
]

const rowId = (field: NumberField) => NUMBER_ROWS.find((row) => row.field === field)?.id ?? field

export function Settings() {
  const { t } = useTranslation()
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [edits, setEdits] = useState<Draft | null>(null)
  const [shown, setShown] = useState<ReadonlySet<NumberField>>(() => new Set())
  const [justSaved, setJustSaved] = useState(false)
  const submitted = useRef<Draft | null>(null)

  const draft = edits ?? (settings.data ? toDraft(settings.data) : null)
  const problems = draft ? validate(draft) : {}
  const changed = draft && settings.data ? changedFields(draft, settings.data) : []

  const save = useMutation({
    mutationFn: api.saveSettings,
    onSuccess: (saved) => {
      client.setQueryData(['settings'], saved)
      setEdits((current) => (current === submitted.current ? null : current))
      setJustSaved(true)
    },
  })

  useEffect(() => {
    if (!justSaved) return
    const timer = window.setTimeout(() => setJustSaved(false), SAVED_MS)
    return () => window.clearTimeout(timer)
  }, [justSaved])

  const update = (change: Partial<Draft>) => {
    if (!draft) return
    setEdits({ ...draft, ...change })
    setJustSaved(false)
    if (save.isError) save.reset()
  }

  const discard = () => {
    setEdits(null)
    setShown(new Set())
    save.reset()
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!draft || changed.length === 0 || save.isPending) return
    const failing = NUMBER_FIELDS.filter((field) => problems[field])
    if (failing.length > 0) {
      setShown(new Set([...shown, ...failing]))
      document.getElementById(rowId(failing[0]))?.focus()
      return
    }
    submitted.current = edits
    save.mutate(toChange(draft, changed))
  }

  const saveError = save.error ? (save.error instanceof ApiError ? errorText(t, save.error.error) : t('errors.unknown')) : null

  return (
    <main className={`page ${styles.settings}`}>
      <h1 className="page-title">{t('settings.title')}</h1>

      {!draft || !settings.data ? (
        <p className={styles.state}>
          <Lamp color={settings.isError ? 'failed' : 'active'} pulse={!settings.isError} />
          {settings.isError ? t('errors.network') : t('settings.loading')}
        </p>
      ) : (
        <>
          <form className={styles.plate} onSubmit={submit} noValidate aria-labelledby="shared-title">
            <header className={styles.head}>
              <h2 id="shared-title" className={styles.title}>{t('settings.shared')}</h2>
              <p className={styles.hint}>{t('settings.sharedHint')}</p>
            </header>

            {NUMBER_ROWS.map((row) => {
              const problem = shown.has(row.field) ? problems[row.field] : undefined
              const value = parseWhole(draft[row.field])
              const { min, max } = LIMITS[row.field]
              const label = t(row.label)
              return (
                <Row key={row.field} id={row.id} label={label} hint={t(row.hint)}
                  error={problem ? t(problem.key, problem.params) : null}>
                  <NumberStepper id={row.id} value={draft[row.field]} min={min} max={max} unit={row.unit && t(row.unit)}
                    atMin={value !== null && value <= min} atMax={max !== undefined && value !== null && value >= max}
                    invalid={problem !== undefined}
                    describedBy={problem ? `${row.id}-hint ${row.id}-error` : `${row.id}-hint`}
                    decreaseLabel={t('action.named', { action: t('settings.decrease'), name: label })}
                    increaseLabel={t('action.named', { action: t('settings.increase'), name: label })}
                    onChange={(text) => update({ [row.field]: text } as Partial<Draft>)}
                    onStep={(delta) => update({ [row.field]: stepValue(row.field, draft[row.field], delta) } as Partial<Draft>)}
                    onBlur={() => setShown((all) => new Set(all).add(row.field))} />
                </Row>
              )
            })}

            <Row id="proxies" label={t('settings.useProxies')} hint={t('settings.useProxiesHint')} error={null}>
              <Switch id="proxies" checked={draft.useProxies} describedBy="proxies-hint"
                onCheckedChange={(checked) => update({ useProxies: checked })} />
            </Row>

            <div className={`${styles.footer} ${changed.length > 0 || saveError ? styles.pinned : ''}`}>
              {saveError ? (
                <p className={`${styles.status} ${styles.failed}`} role="alert">
                  <span className={styles.statusText}>
                    <Lamp color="failed" />
                    {saveError}
                  </span>
                </p>
              ) : (
                <p className={styles.status} role="status">
                  {changed.length > 0 ? (
                    <span key="dirty" className={`${styles.statusText} ${styles.dirty}`}>
                      <Lamp color="active" />
                      {t('settings.unsaved', { count: changed.length })}
                    </span>
                  ) : justSaved ? (
                    <span key="saved" className={`${styles.statusText} ${styles.dirty}`}>
                      <Lamp color="done" />
                      {t('settings.saved')}
                    </span>
                  ) : (
                    <span key="clean" className={styles.statusText}>{t('settings.applyHint')}</span>
                  )}
                </p>
              )}
              <div className={styles.actions}>
                {changed.length > 0 && (
                  <button type="button" className={`${controls.button} ${styles.discard}`} onClick={discard}
                    disabled={save.isPending}>
                    {t('settings.discard')}
                  </button>
                )}
                <button type="submit" className={`${controls.button} ${changed.length > 0 ? controls.primary : ''}`}
                  disabled={changed.length === 0} aria-busy={save.isPending || undefined}>
                  {save.isPending && <span className={controls.spinner} aria-hidden="true" />}
                  {t('settings.save')}
                </button>
              </div>
            </div>
          </form>

          <StoragePlate root={settings.data.download_root} />
        </>
      )}

      <section className={styles.plate} aria-labelledby="other-title">
        <header className={styles.head}>
          <h2 id="other-title" className={styles.title}>{t('settings.other')}</h2>
        </header>
        <LanguageRow />
      </section>
    </main>
  )
}

interface RowProps {
  id: string
  label: string
  hint: string
  error: string | null
  children: ReactNode
}

// - One setting: its name and what it does, any problem with its value, then its control.
function Row({ id, label, hint, error, children }: RowProps) {
  return (
    <div className={styles.row}>
      <div className={styles.text}>
        <label htmlFor={id} className={styles.label}>{label}</label>
        <span id={`${id}-hint`} className={styles.hint}>{hint}</span>
        {error && <span id={`${id}-error`} className={styles.error}>{error}</span>}
      </div>
      <div className={styles.control}>{children}</div>
    </div>
  )
}

// - The download folder, and how much of its filesystem is used, from the same storage query
//   the navigation bar reads.
function StoragePlate({ root }: { root: string }) {
  const { t, i18n } = useTranslation()
  const storage = useQuery({ queryKey: STORAGE_KEY, queryFn: api.storage, staleTime: Infinity }).data
  const used = storage && storage.total_bytes > 0 ? 1 - storage.free_bytes / storage.total_bytes : null

  return (
    <section className={styles.plate} aria-labelledby="storage-title">
      <header className={styles.head}>
        <h2 id="storage-title" className={styles.title}>{t('settings.storage')}</h2>
      </header>
      <div className={styles.row}>
        <div className={styles.text}>
          <span className={styles.label}>{t('settings.root')}</span>
          <span className={styles.hint}>{t('settings.rootHint')}</span>
        </div>
        <span className={styles.path}>{root}</span>
      </div>
      {storage && used !== null && (
        <div className={styles.meterRow}>
          <div className={styles.meter} aria-hidden="true">
            <div className={styles.meterFill} style={{ transform: `scaleX(${used})` }} />
          </div>
          <span className={styles.free}>
            {t('settings.storageFree', {
              free: formatStorage(i18n.language, storage.free_bytes),
              total: formatStorage(i18n.language, storage.total_bytes),
            })}
          </span>
        </div>
      )}
    </section>
  )
}

function LanguageRow() {
  const { t, i18n } = useTranslation()
  return (
    <div className={styles.row}>
      <div className={styles.text}>
        <span id="language-label" className={styles.label}>{t('settings.language')}</span>
        <span id="language-hint" className={styles.hint}>{t('settings.languageHint')}</span>
      </div>
      <div className={styles.control}>
        <SegmentedControl labelledBy="language-label" describedBy="language-hint" value={toSupported(i18n.language)} onChange={chooseLanguage}
          options={LANGUAGES.map((language) => ({ value: language, label: t(`language.${language}`), lang: language }))} />
      </div>
    </div>
  )
}
