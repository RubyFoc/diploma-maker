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

  it('renders a brand-new draft (no accepted content yet) as plain text, not all-green diff markup', () => {
    const { container } = render(
      <DiffViewer before="" after={'First paragraph.\n\nSecond paragraph.'} onAccept={vi.fn()} onReject={vi.fn()} />,
    )
    const page = visiblePage(container)

    const segments = page.getAllByTestId('diff-segment-added')
    for (const segment of segments) {
      expect(segment).not.toHaveClass('diff-added')
    }
    expect(screen.getByText(strings.diffNewDraftHintMessage)).toBeInTheDocument()
  })

  it('renders the reroute banner when rerouteNotice is set', () => {
    render(
      <DiffViewer
        before={before}
        after={after}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        rerouteNotice={{ requestedBlockId: 'b1', usedBlockId: 'b2' }}
      />,
    )

    expect(screen.getByText(strings.diffRerouteNoticeMessage)).toBeInTheDocument()
  })

  it('does not render the reroute banner when rerouteNotice is null/omitted', () => {
    render(<DiffViewer before={before} after={after} onAccept={vi.fn()} onReject={vi.fn()} />)

    expect(screen.queryByText(strings.diffRerouteNoticeMessage)).not.toBeInTheDocument()
  })

  describe('undo/redo history controls (TASK-E16-5)', () => {
    // `before`/`after` for these tests describe an anchor-mode insertion (the only case that
    // ever records history) — one added block, no removals — so the "after" manifest lines up
    // one-to-one with the tagged blocks, matching real usage.
    const insertBefore = 'first paragraph'
    const insertAfter = 'first paragraph\ninserted paragraph'
    const manifest = [
      { id: 'b1', content: 'first paragraph', content_hash: 'h1', order: 0 },
      { id: 'b2', content: 'inserted paragraph', content_hash: 'h2', order: 1 },
    ]

    it('hides the controls entirely when history is null', () => {
      render(<DiffViewer before={insertBefore} after={insertAfter} onAccept={vi.fn()} onReject={vi.fn()} manifest={manifest} />)

      expect(screen.queryByLabelText(strings.historyControlsTitle)).not.toBeInTheDocument()
    })

    it('hides the controls entirely when there is no recorded history yet', () => {
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={{ operations: [], appliedCount: 0, totalOperations: 0 }}
        />,
      )

      expect(screen.queryByLabelText(strings.historyControlsTitle)).not.toBeInTheDocument()
    })

    it('disables undo controls when nothing is applied, and redo controls when nothing is undone', () => {
      const history = { operations: [{ id: 'o1', block_id: 'b2', created_at: 'now' }], appliedCount: 1, totalOperations: 1 }
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={history}
        />,
      )

      expect(screen.getByRole('button', { name: strings.historyRedoLastButton })).toBeDisabled()
      expect(screen.getByRole('button', { name: strings.historyRedoAllButton })).toBeDisabled()
      expect(screen.getByRole('button', { name: strings.historyUndoLastButton })).toBeEnabled()
      expect(screen.getByRole('button', { name: strings.historyUndoAllButton })).toBeEnabled()
    })

    it('"Undo last edit" calls onUndo with count 1', () => {
      const onUndo = vi.fn()
      const history = { operations: [{ id: 'o1', block_id: 'b2', created_at: 'now' }], appliedCount: 1, totalOperations: 1 }
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={history}
          onUndo={onUndo}
        />,
      )

      fireEvent.click(screen.getByRole('button', { name: strings.historyUndoLastButton }))

      expect(onUndo).toHaveBeenCalledWith(1)
    })

    it('"Undo entire document" calls onUndo with the full applied count', () => {
      const onUndo = vi.fn()
      const history = {
        operations: [
          { id: 'o1', block_id: 'b2', created_at: 'now' },
          { id: 'o2', block_id: 'b3', created_at: 'now' },
        ],
        appliedCount: 2,
        totalOperations: 2,
      }
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={history}
          onUndo={onUndo}
        />,
      )

      fireEvent.click(screen.getByRole('button', { name: strings.historyUndoAllButton }))

      expect(onUndo).toHaveBeenCalledWith(2)
    })

    it('"Redo entire document" calls onRedo with the remaining redo-tail count', () => {
      const onRedo = vi.fn()
      const history = {
        operations: [
          { id: 'o1', block_id: 'b2', created_at: 'now' },
          { id: 'o2', block_id: 'b3', created_at: 'now' },
        ],
        appliedCount: 0,
        totalOperations: 2,
      }
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={history}
          onRedo={onRedo}
        />,
      )

      fireEvent.click(screen.getByRole('button', { name: strings.historyRedoAllButton }))

      expect(onRedo).toHaveBeenCalledWith(2)
    })

    it('disables "Undo this page" when the page has nothing to revert', () => {
      // The tail operation touches a block that isn't part of this draft's manifest at all
      // (e.g. some other page) — the resolved page-count is 0.
      const history = { operations: [{ id: 'o1', block_id: 'unrelated-block', created_at: 'now' }], appliedCount: 1, totalOperations: 1 }
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={history}
        />,
      )

      expect(screen.getByRole('button', { name: strings.historyUndoPageButton })).toBeDisabled()
    })

    it('"Undo this page" fires immediately when the page\'s edits are plainly contiguous', () => {
      const onUndo = vi.fn()
      const history = { operations: [{ id: 'o1', block_id: 'b2', created_at: 'now' }], appliedCount: 1, totalOperations: 1 }
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={history}
          onUndo={onUndo}
        />,
      )

      fireEvent.click(screen.getByRole('button', { name: strings.historyUndoPageButton }))

      expect(onUndo).toHaveBeenCalledWith(1)
    })

    it('"Undo this page" requires an explicit second confirm click before reverting operations elsewhere', () => {
      const onUndo = vi.fn()
      // Tail is an unrelated block; this page's other match ('b1') sits further back, separated
      // by that unrelated operation — reverting the whole page also undoes the unrelated one.
      const history = {
        operations: [
          { id: 'o1', block_id: 'b2', created_at: 'now' },
          { id: 'o2', block_id: 'other', created_at: 'now' },
          { id: 'o3', block_id: 'b1', created_at: 'now' },
        ],
        appliedCount: 3,
        totalOperations: 3,
      }
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={history}
          onUndo={onUndo}
        />,
      )

      fireEvent.click(screen.getByRole('button', { name: strings.historyUndoPageButton }))

      expect(onUndo).not.toHaveBeenCalled()
      const confirmButton = screen.getByRole('button', { name: strings.historyPageUndoConfirmButton(1) })

      fireEvent.click(confirmButton)

      expect(onUndo).toHaveBeenCalledWith(3)
    })

    it('"Redo this page" requires an explicit second confirm click before reapplying operations elsewhere', () => {
      const onRedo = vi.fn()
      const history = {
        operations: [
          { id: 'o1', block_id: 'b1', created_at: 'now' },
          { id: 'o2', block_id: 'other', created_at: 'now' },
          { id: 'o3', block_id: 'b2', created_at: 'now' },
        ],
        appliedCount: 0,
        totalOperations: 3,
      }
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={history}
          onRedo={onRedo}
        />,
      )

      fireEvent.click(screen.getByRole('button', { name: strings.historyRedoPageButton }))

      expect(onRedo).not.toHaveBeenCalled()
      const confirmButton = screen.getByRole('button', { name: strings.historyPageRedoConfirmButton(1) })

      fireEvent.click(confirmButton)

      expect(onRedo).toHaveBeenCalledWith(3)
    })

    it('shows a distinct message for a 409 conflict', () => {
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={{ operations: [{ id: 'o1', block_id: 'b2', created_at: 'now' }], appliedCount: 1, totalOperations: 1 }}
          historyError="conflict"
        />,
      )

      expect(screen.getByText(strings.historyConflictErrorMessage)).toBeInTheDocument()
      expect(screen.queryByText(strings.historyGenericErrorMessage)).not.toBeInTheDocument()
    })

    it('shows a generic message for a non-conflict error', () => {
      render(
        <DiffViewer
          before={insertBefore}
          after={insertAfter}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          manifest={manifest}
          history={{ operations: [{ id: 'o1', block_id: 'b2', created_at: 'now' }], appliedCount: 1, totalOperations: 1 }}
          historyError="generic"
        />,
      )

      expect(screen.getByText(strings.historyGenericErrorMessage)).toBeInTheDocument()
    })
  })
})
