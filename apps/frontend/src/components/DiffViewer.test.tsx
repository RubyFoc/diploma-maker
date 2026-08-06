import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DiffViewer } from './DiffViewer'
import { strings } from '../strings'

// See DocumentPreview.test.tsx: `PaginatedDocument` renders an off-screen, `aria-hidden`
// measuring pass alongside the visible page, so plain testid queries would match twice.
function visiblePage(container: HTMLElement) {
  const page = container.querySelector('.document-page:not(.document-page--measure)')
  if (!page) {
    throw new Error('visible .document-page not found')
  }
  return within(page as HTMLElement)
}

describe('DiffViewer', () => {
  const before = 'keep me\nremove me'
  const after = 'keep me\nadded line'

  it('renders added, removed, and unchanged segments distinguishably', () => {
    const { container } = render(<DiffViewer before={before} after={after} onAccept={vi.fn()} onReject={vi.fn()} />)
    const page = visiblePage(container)

    const unchanged = page.getByTestId('diff-segment-unchanged')
    const added = page.getByTestId('diff-segment-added')
    const removed = page.getByTestId('diff-segment-removed')

    expect(unchanged).toHaveTextContent('keep me')
    expect(added).toHaveTextContent('added line')
    expect(removed).toHaveTextContent('remove me')

    expect(added).toHaveClass('diff-added')
    expect(removed).toHaveClass('diff-removed')
    expect(unchanged).toHaveClass('diff-unchanged')
  })

  it('calls onAccept when the accept button is clicked', () => {
    const onAccept = vi.fn()
    render(<DiffViewer before={before} after={after} onAccept={onAccept} onReject={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: strings.diffAcceptButton }))

    expect(onAccept).toHaveBeenCalledTimes(1)
  })

  it('calls onReject when the reject button is clicked', () => {
    const onReject = vi.fn()
    render(<DiffViewer before={before} after={after} onAccept={vi.fn()} onReject={onReject} />)

    fireEvent.click(screen.getByRole('button', { name: strings.diffRejectButton }))

    expect(onReject).toHaveBeenCalledTimes(1)
  })

  it('renders an empty state when both versions are empty', () => {
    render(<DiffViewer before="" after="" onAccept={vi.fn()} onReject={vi.fn()} />)

    expect(screen.getByText(strings.diffEmpty)).toBeInTheDocument()
  })
})
