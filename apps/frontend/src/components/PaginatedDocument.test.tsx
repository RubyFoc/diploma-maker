import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
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
})
