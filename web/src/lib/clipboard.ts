// - Puts text on the clipboard and reports whether it got there.
// - The async Clipboard API exists only in a secure context, and the app is usually reached
//   over plain http on the LAN. Without it, or when it refuses the write, the text goes
//   through a hidden, selected textarea and `document.execCommand('copy')`.

export async function copyText(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // - Falls through to the textarea copy below.
    }
  }
  const field = document.createElement('textarea')
  field.value = text
  field.setAttribute('readonly', '')
  field.style.position = 'fixed'
  field.style.opacity = '0'
  document.body.append(field)
  const focused = document.activeElement as HTMLElement | null
  field.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    field.remove()
    focused?.focus()
  }
}
