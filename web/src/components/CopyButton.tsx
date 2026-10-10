import { useEffect, useState } from 'react'
import { copyText } from '../lib/clipboard'
import { IconButton } from './IconButton'
import { useToast } from './toast-context'

// - An icon button that puts `text` on the clipboard.
// - After a copy it shows a check for COPIED_MS from the latest copy and announces `copied`; a
//   failed copy raises `failed` as an error toast.

export const COPIED_MS = 1600

interface Props {
  text: string
  label: string
  tooltip?: string
  copied: string
  failed: string
}

export function CopyButton({ text, label, tooltip, copied: copiedText, failed }: Props) {
  const toast = useToast()
  const [copies, setCopies] = useState(0)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), COPIED_MS)
    return () => window.clearTimeout(timer)
  }, [copied, copies])

  const copy = async () => {
    if (await copyText(text)) {
      setCopied(true)
      setCopies((n) => n + 1)
    } else {
      toast(failed, 'error')
    }
  }

  return (
    <>
      <IconButton icon={copied ? 'check' : 'copy'} label={label} tooltip={tooltip} onClick={copy} />
      <span className="visually-hidden" role="status">{copied ? copiedText : ''}</span>
    </>
  )
}
