import { Trans, useTranslation } from 'react-i18next'
import { Lamp, type LampColor } from '../components/Lamp'
import type { BatchView, RowState } from '../lib/batch'
import { formatBytes, formatStorage } from '../lib/format'
import { BATCH_LIMIT, type Batch } from '../lib/url'
import controls from '../styles/controls.module.css'
import styles from './Home.module.css'

// - The preview of a pasted batch: one row per supported link, in paste order, then the total
//   size of the files that can start against the NAS free space, and one button for all of them.
// - Each row is a lamp, the file name, the host and the row's state, and the file size. A
//   skipped row says why. While the batch starts, rows switch to their outcome one by one.
// - Notes say how many other links were left out: unsupported ones and those past the limit.
// - The button stays disabled while a link is being checked or the set does not fit.

interface Props {
  batch: Batch
  view: BatchView
  free: number
  locale: string
  starting: boolean
  onStart: () => void
}

function lampOf(state: RowState): LampColor {
  if (state.kind === 'checking') return 'amber'
  if (state.kind === 'ready' || state.kind === 'started') return 'green'
  if (state.kind === 'skipped' && !state.error) return 'steel'
  return 'red'
}

export function BatchPreview({ batch, view, free, locale, starting, onStart }: Props) {
  const { t } = useTranslation()

  const detail = (state: RowState) => {
    switch (state.kind) {
      case 'checking':
        return t('batch.row.checking')
      case 'ready':
        return t('batch.row.ready')
      case 'started':
        return t('batch.row.started')
      default:
        return state.text
    }
  }

  return (
    <section className={styles.preview} aria-label={t('batch.label', { count: batch.links.length })}>
      <ul className={styles.batchList}>
        {view.rows.map(({ item, state }) => {
          const name = item.data?.file_name ?? item.link.url
          const failing = state.kind === 'failed' || (state.kind === 'skipped' && state.error)
          return (
            <li key={item.link.key} className={styles.batchRow}>
              <span className={styles.batchLamp}>
                <Lamp color={lampOf(state)} pulse={state.kind === 'checking'} />
              </span>
              <p className={styles.batchName} title={name}>{name}</p>
              <p className={`${styles.batchDetail} ${failing ? styles.noteError : ''}`}>
                {item.link.provider.name} · {detail(state)}
              </p>
              <span className={`${styles.batchSize} num`}>
                {item.data?.size == null ? '' : formatBytes(locale, item.data.size)}
              </span>
            </li>
          )
        })}
      </ul>
      {batch.ignored > 0 && <p className={styles.batchNote}>{t('batch.ignored', { count: batch.ignored })}</p>}
      {batch.dropped > 0 && (
        <p className={styles.batchNote}>{t('batch.dropped', { limit: BATCH_LIMIT, count: batch.dropped })}</p>
      )}
      {view.ready.length > 0 && !view.started && (
        <dl className={styles.facts}>
          <div className={styles.fact}>
            <dt>{t('batch.total')}</dt>
            <dd className="num">{formatBytes(locale, view.total)}</dd>
          </div>
          <div className={styles.fact}>
            <dt>{t('nav.storage')}</dt>
            <dd className="num">{formatStorage(locale, free)}</dd>
          </div>
        </dl>
      )}
      {view.short > 0 && !view.started && (
        <p className={`${styles.note} ${styles.noteError}`}>
          {t('batch.short', { size: formatBytes(locale, view.short) })}
        </p>
      )}
      <div className={styles.actions}>
        {view.ready.length > 0 && (!view.started || starting) && (
          <button type="button" className={`${controls.button} ${controls.primary}`} onClick={onStart}
            disabled={!view.canStart && !starting} aria-busy={starting || undefined}>
            {starting && <span className={controls.spinner} aria-hidden="true" />}
            {t('batch.download', { count: view.ready.length })}
          </button>
        )}
        <span className={styles.keys}>
          <Trans i18nKey={view.enterStarts ? 'preview.keys' : 'preview.keysClear'} components={{ key: <kbd /> }} />
        </span>
      </div>
    </section>
  )
}
