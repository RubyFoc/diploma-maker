import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DiffViewer } from './DiffViewer'
import { strings } from '../strings'

describe('DiffViewer', () => {
  const before = 'keep me\nremove me'
  const after = 'keep me\nadded line'

  it('renders added, removed, and unchanged segments distinguishably', () => {
    render(<DiffViewer before={before} after={after} onAccept={vi.fn()} onReject={vi.fn()} />)

    const unchanged = screen.getByTestId('diff-segment-unchanged')
    const added = screen.getByTestId('diff-segment-added')
    const removed = screen.getByTestId('diff-segment-removed')

    expect(unchanged).toHaveTextContent('keep me')
    expect(added).toHaveTextContent('added line')
    expect(removed).toHaveTextContent('remove me')

    expect(added).toHaveClass('diff-segment--added')
    expect(removed).toHaveClass('diff-segment--removed')
    expect(unchanged).toHaveClass('diff-segment--unchanged')
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
