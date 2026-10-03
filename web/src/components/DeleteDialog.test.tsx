import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { DeleteDialog } from './DeleteDialog'

// - A button opens the dialog through state, the way the files page does.

function Harness({ onConfirm }: { onConfirm: (deleteFile: boolean) => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Delete: a.rar</button>
      <DeleteDialog name="a.rar" canDeleteFile open={open} onOpenChange={setOpen}
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

describe('DeleteDialog', () => {
  it('gives focus back to the button that opened it', async () => {
    const user = userEvent.setup()
    render(<Harness onConfirm={vi.fn()} />)
    const opener = screen.getByRole('button', { name: 'Delete: a.rar' })
    await user.click(opener)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(opener).toHaveFocus()
  })

  it('confirms with the file option as chosen', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(<Harness onConfirm={onConfirm} />)
    await user.click(screen.getByRole('button', { name: 'Delete: a.rar' }))
    await user.click(await screen.findByRole('checkbox', { name: 'Also delete the file on the NAS' }))
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalledWith(true)
  })
})
