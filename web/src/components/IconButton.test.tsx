import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Tooltip } from 'radix-ui'
import { describe, expect, it, vi } from 'vitest'
import { IconButton } from './IconButton'

describe('IconButton', () => {
  it('keeps a disabled button as the only tab stop, announced as disabled, with its tooltip, ignoring clicks', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(
      <Tooltip.Provider>
        <IconButton icon="delete" label="Delete: a.rar" tooltip="Moved or deleted from the NAS" onClick={onClick} disabled />
      </Tooltip.Provider>,
    )
    const button = screen.getByRole('button', { name: 'Delete: a.rar' })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    await user.tab()
    expect(button).toHaveFocus()
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Moved or deleted from the NAS')
    await user.tab()
    expect(document.body).toHaveFocus()
    await user.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })
})
