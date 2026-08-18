import { useState } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PaginatedDocument } from './PaginatedDocument'
import { strings } from '../strings'
import type { Block } from '../utils/renderMarkdownPreview'

function visiblePage(container: HTMLElement) {
  const page = container.querySelector('.document-page:not(.document-page--measure)')
  if (!page) {
    throw new Error('visible .document-page not found')
  }
  return within(page as HTMLElement)
}

const pageStyle = { width: '210mm', height: '297mm', padding: '25mm' }

describe('PaginatedDocument', () => {
  it('renders the empty message and no page nav when there are no blocks', () => {
    render(<PaginatedDocument blocks={[]} pageStyle={pageStyle} emptyMessage="Nothing here yet." />)

    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /prev/i })).not.toBeInTheDocument()
  })

  it('renders every block on the single page when content fits (jsdom reports zero heights)', () => {
    const blocks: Block[] = [
      { kind: 'h1', text: 'Title' },
      { kind: 'p', text: 'Some paragraph text.' },
    ]
    const { container } = render(<PaginatedDocument blocks={blocks} pageStyle={pageStyle} />)
    const page = visiblePage(container)

    expect(page.getByRole('heading', { level: 1, name: 'Title' })).toBeInTheDocument()
    expect(page.getByText('Some paragraph text.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /prev/i })).not.toBeInTheDocument()
  })

  it('applies a custom renderBlock override', () => {
    const blocks: Block[] = [{ kind: 'p', text: 'wrapped' }]
    const { container } = render(
      <PaginatedDocument
        blocks={blocks}
        pageStyle={pageStyle}
        renderBlock={(block, key) => (
          <span key={key} data-testid="custom-block">
            {block.kind === 'p' ? block.text : ''}
          </span>
        )}
      />,
    )
    const page = visiblePage(container)

    expect(page.getByTestId('custom-block')).toHaveTextContent('wrapped')
  })

  it('renders a lock toggle per block when lockSelection is provided, reflecting locked state', () => {
    const blocks: Block[] = [{ kind: 'p', text: 'First paragraph.' }, { kind: 'p', text: 'Second paragraph.' }]
    const lockableBlocks = [
      { id: 'b1', content: 'First paragraph.', content_hash: 'h1', order: 0 },
      { id: 'b2', content: 'Second paragraph.', content_hash: 'h2', order: 1 },
    ]
    const { container } = render(
      <PaginatedDocument
        blocks={blocks}
        pageStyle={pageStyle}
        lockSelection={{
          lockableBlocks,
          lockedBlockIds: new Set(['b1']),
          onToggleLock: vi.fn(),
        }}
      />,
    )
    const page = visiblePage(container)

    expect(page.getByRole('button', { name: strings.documentBlockUnlockLabel })).toBeInTheDocument()
    expect(page.getByRole('button', { name: strings.documentBlockLockLabel })).toBeInTheDocument()
  })

  it('calls onToggleLock with the matching manifest block when its toggle is clicked', () => {
    const blocks: Block[] = [{ kind: 'p', text: 'First paragraph.' }]
    const lockableBlocks = [{ id: 'b1', content: 'First paragraph.', content_hash: 'h1', order: 0 }]
    const onToggleLock = vi.fn()
    const { container } = render(
      <PaginatedDocument
        blocks={blocks}
        pageStyle={pageStyle}
        lockSelection={{ lockableBlocks, lockedBlockIds: new Set(), onToggleLock }}
      />,
    )
    const page = visiblePage(container)

    fireEvent.click(page.getByRole('button', { name: strings.documentBlockLockLabel }))

    expect(onToggleLock).toHaveBeenCalledWith(lockableBlocks[0])
  })

  it('renders no lock toggles when lockSelection is omitted', () => {
    const blocks: Block[] = [{ kind: 'p', text: 'First paragraph.' }]
    const { container } = render(<PaginatedDocument blocks={blocks} pageStyle={pageStyle} />)
    const page = visiblePage(container)

    expect(page.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders an "insert here" toggle per block when anchorSelection is provided, reflecting the selected block', () => {
    const blocks: Block[] = [{ kind: 'p', text: 'First paragraph.' }, { kind: 'p', text: 'Second paragraph.' }]
    const anchorableBlocks = [
      { id: 'b1', content: 'First paragraph.', content_hash: 'h1', order: 0 },
      { id: 'b2', content: 'Second paragraph.', content_hash: 'h2', order: 1 },
    ]
    const { container } = render(
      <PaginatedDocument
        blocks={blocks}
        pageStyle={pageStyle}
        anchorSelection={{ anchorableBlocks, selectedBlockId: 'b1', onSelect: vi.fn() }}
      />,
    )
    const page = visiblePage(container)

    expect(page.getByRole('button', { name: strings.documentBlockInsertHereSelectedLabel })).toBeInTheDocument()
    expect(page.getByRole('button', { name: strings.documentBlockInsertHereLabel })).toBeInTheDocument()
  })

  it('calls onSelect with the matching manifest block when its "insert here" toggle is clicked', () => {
    const blocks: Block[] = [{ kind: 'p', text: 'First paragraph.' }]
    const anchorableBlocks = [{ id: 'b1', content: 'First paragraph.', content_hash: 'h1', order: 0 }]
    const onSelect = vi.fn()
    const { container } = render(
      <PaginatedDocument
        blocks={blocks}
        pageStyle={pageStyle}
        anchorSelection={{ anchorableBlocks, selectedBlockId: null, onSelect }}
      />,
    )
    const page = visiblePage(container)

    fireEvent.click(page.getByRole('button', { name: strings.documentBlockInsertHereLabel }))

    expect(onSelect).toHaveBeenCalledWith(anchorableBlocks[0])
  })

  it('renders both lock and anchor toggles together when both selections are provided', () => {
    const blocks: Block[] = [{ kind: 'p', text: 'First paragraph.' }]
    const manifestBlocks = [{ id: 'b1', content: 'First paragraph.', content_hash: 'h1', order: 0 }]
    const { container } = render(
      <PaginatedDocument
        blocks={blocks}
        pageStyle={pageStyle}
        lockSelection={{ lockableBlocks: manifestBlocks, lockedBlockIds: new Set(), onToggleLock: vi.fn() }}
        anchorSelection={{ anchorableBlocks: manifestBlocks, selectedBlockId: null, onSelect: vi.fn() }}
      />,
    )
    const page = visiblePage(container)

    expect(page.getByRole('button', { name: strings.documentBlockLockLabel })).toBeInTheDocument()
    expect(page.getByRole('button', { name: strings.documentBlockInsertHereLabel })).toBeInTheDocument()
  })

  it('calls onPageBlockIdsChange with the visible page block ids, skipping nulls (TASK-E16-4)', () => {
    const blocks: Block[] = [
      { kind: 'p', text: 'First paragraph.' },
      { kind: 'p', text: 'Second paragraph.' },
    ]
    const onPageBlockIdsChange = vi.fn()
    render(
      <PaginatedDocument
        blocks={blocks}
        pageStyle={pageStyle}
        pageBlockIds={['b1', null]}
        onPageBlockIdsChange={onPageBlockIdsChange}
      />,
    )

    expect(onPageBlockIdsChange).toHaveBeenCalledWith(['b1'])
  })

  it('does not call onPageBlockIdsChange when pageBlockIds is omitted', () => {
    const blocks: Block[] = [{ kind: 'p', text: 'First paragraph.' }]
    const onPageBlockIdsChange = vi.fn()
    render(<PaginatedDocument blocks={blocks} pageStyle={pageStyle} onPageBlockIdsChange={onPageBlockIdsChange} />)

    expect(onPageBlockIdsChange).toHaveBeenCalledWith([])
  })

  describe('pagination accounts for the lock/anchor toggle narrowing a block\'s rendered width', () => {
    // Simulates the real-world effect this test guards against: a block wrapped in the
    // lock/anchor toggle's flex row (`.document-block-with-lock`) renders narrower — its text
    // wraps onto more lines — so it's genuinely taller than the same block with no toggle beside
    // it. jsdom does no real layout, so this mock stands in for that: any measured element
    // containing `.document-block-with-lock` reports the "wrapped-narrower" height; any element
    // without it (the pre-fix off-screen measuring pass, which rendered blocks with no toggle at
    // all) reports the "full-width" height instead — under-measuring relative to what the real,
    // toggle-narrowed page actually needs.
    beforeEach(() => {
      Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
        configurable: true,
        get(this: HTMLElement) {
          return this.querySelector('.document-block-with-lock') ? 60 : 30
        },
      })
      Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 100 })
    })

    afterEach(() => {
      Reflect.deleteProperty(HTMLElement.prototype, 'offsetHeight')
      Reflect.deleteProperty(HTMLElement.prototype, 'clientHeight')
    })

    it('measures each block at its real (toggle-narrowed) height, splitting one block per page instead of overflowing one page', () => {
      const blocks: Block[] = [
        { kind: 'p', text: 'First paragraph.' },
        { kind: 'p', text: 'Second paragraph.' },
        { kind: 'p', text: 'Third paragraph.' },
      ]
      const lockableBlocks = [
        { id: 'b1', content: 'First paragraph.', content_hash: 'h1', order: 0 },
        { id: 'b2', content: 'Second paragraph.', content_hash: 'h2', order: 1 },
        { id: 'b3', content: 'Third paragraph.', content_hash: 'h3', order: 2 },
      ]
      render(
        <PaginatedDocument
          blocks={blocks}
          pageStyle={pageStyle}
          lockSelection={{ lockableBlocks, lockedBlockIds: new Set(), onToggleLock: vi.fn() }}
        />,
      )

      // Each block is 60 tall (with its toggle) against a 100-tall page: only one fits per page.
      // If the measuring pass had under-measured them at 30 (no toggle, the pre-fix bug), all
      // three would wrongly fit on a single page and this would show no page nav at all.
      expect(screen.getByText(strings.documentPageLabel(1, 3))).toBeInTheDocument()
    })
  })

  describe('page navigation survives a parent re-render with fresh (but content-identical) props', () => {
    // jsdom always reports 0 for offsetHeight/clientHeight, so every other test's content lands
    // on a single page — force real per-block heights here to get more than one page, matching
    // any real generated/uploaded chapter (which always has a manifest, i.e. always hits this
    // path in production).
    beforeEach(() => {
      Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => 50 })
      Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 100 })
    })

    afterEach(() => {
      Reflect.deleteProperty(HTMLElement.prototype, 'offsetHeight')
      Reflect.deleteProperty(HTMLElement.prototype, 'clientHeight')
    })

    /**
     * Mirrors `DiffViewer`'s real shape: `blocks` and `pageStyle` are rebuilt as new array/object
     * literals on every render (not memoized) rather than passed in as stable props, and
     * `onPageBlockIdsChange` updates this wrapper's own state — the exact feedback loop that
     * used to snap `PaginatedDocument` back to page 1 on every "Next" click (see
     * `PaginatedDocument.tsx`'s `blocksSignature`/`pageStyleSignature` comment).
     */
    function UnmemoizedParent() {
      const [, setVisibleBlockIds] = useState<string[]>([])
      const blocks: Block[] = [
        { kind: 'p', text: 'First paragraph.' },
        { kind: 'p', text: 'Second paragraph.' },
        { kind: 'p', text: 'Third paragraph.' },
      ]
      return (
        <PaginatedDocument
          blocks={blocks}
          pageStyle={{ ...pageStyle }}
          pageBlockIds={['b1', 'b2', 'b3']}
          onPageBlockIdsChange={setVisibleBlockIds}
        />
      )
    }

    it('stays on page 2 after clicking Next, instead of snapping back to page 1', () => {
      const { container } = render(<UnmemoizedParent />)
      const page = () => visiblePage(container)

      expect(page().getByText('First paragraph.')).toBeInTheDocument()
      expect(page().queryByText('Third paragraph.')).not.toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: strings.documentPageNextButton }))

      expect(page().getByText('Third paragraph.')).toBeInTheDocument()
      expect(page().queryByText('First paragraph.')).not.toBeInTheDocument()
    })
  })
})
