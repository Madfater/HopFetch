import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { ConfirmDialog, type ConfirmKind } from './ConfirmDialog'

// - A button opens the dialog through state, the way the files page does.

interface HarnessProps {
  kind?: ConfirmKind
  discards?: number
  onConfirm: (deleteFile: boolean) => void
}

function Harness({ kind = 'delete', discards = 0, onConfirm }: HarnessProps) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open: a.rar</button>
      <ConfirmDialog kind={kind} name="a.rar" discards={discards} canDeleteFile open={open} onOpenChange={setOpen}
        onConfirm={(deleteFile) => {
          onConfirm(deleteFile)
          setOpen(false)
        }} />
    </>
  )
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('ConfirmDialog', () => {
  it('gives focus back to the button that opened it', async () => {
    const user = userEvent.setup()
    render(<Harness onConfirm={vi.fn()} />)
    const opener = screen.getByRole('button', { name: 'Open: a.rar' })
    await user.click(opener)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(opener).toHaveFocus()
  })

  it.each<ConfirmKind>(['delete', 'cancel'])('opens the %s dialog with focus on Keep', async (kind) => {
    const user = userEvent.setup()
    render(<Harness kind={kind} onConfirm={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Open: a.rar' }))
    await screen.findByRole('dialog')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Keep' })).toHaveFocus())
  })

  it('confirms with the file option as chosen', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(<Harness onConfirm={onConfirm} />)
    await user.click(screen.getByRole('button', { name: 'Open: a.rar' }))
    await user.click(await screen.findByRole('checkbox', { name: 'Also delete the file on the NAS' }))
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalledWith(true)
  })

  it('states the downloaded bytes it discards', async () => {
    const user = userEvent.setup()
    render(<Harness kind="cancel" discards={1.31 * 2 ** 30} onConfirm={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Open: a.rar' }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel download' })
    expect(dialog).toHaveAccessibleDescription(expect.stringContaining('This discards the 1.31 GB downloaded so far.'))
    expect(dialog).toHaveAccessibleDescription(expect.stringMatching(/^a\.rar\s*Stop this download\./))
    expect(screen.getByRole('button', { name: 'Keep' })).toHaveFocus()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('leaves the cost out when nothing was downloaded', async () => {
    const user = userEvent.setup()
    render(<Harness kind="cancel" onConfirm={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Open: a.rar' }))
    await screen.findByRole('dialog')
    expect(screen.queryByText(/This discards/)).not.toBeInTheDocument()
  })
})
