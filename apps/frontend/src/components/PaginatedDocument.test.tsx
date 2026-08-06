import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PaginatedDocument } from './PaginatedDocument'
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
})
