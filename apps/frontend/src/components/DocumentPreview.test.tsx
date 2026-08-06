import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DocumentPreview } from './DocumentPreview'
import { strings } from '../strings'

// `PaginatedDocument` renders an off-screen, `aria-hidden` measuring pass alongside the
// visible page to compute pagination — both contain the same content, so plain
// `screen.getByText`/`getByTestId` queries (which aren't `aria-hidden`-aware, unlike
// `getByRole`) would match twice. Scope queries to just the visible page.
function visiblePage(container: HTMLElement) {
  const page = container.querySelector('.document-page:not(.document-page--measure)')
  if (!page) {
    throw new Error('visible .document-page not found')
  }
  return within(page as HTMLElement)
}

describe('DocumentPreview', () => {
  it('renders the empty-state string when content is empty', () => {
    render(<DocumentPreview content="" />)

    expect(screen.getByText(strings.chapterContentEmpty)).toBeInTheDocument()
  })

  it('renders formatted Markdown content as headings, paragraphs, and lists', () => {
    const { container } = render(
      <DocumentPreview content={'# Chapter One\n\nSome **bold** prose.\n\n- item one\n- item two'} />,
    )
    const page = visiblePage(container)

    expect(page.getByRole('heading', { level: 1, name: 'Chapter One' })).toBeInTheDocument()
    expect(page.getByText('bold').tagName).toBe('STRONG')
    expect(page.getByRole('list').tagName).toBe('UL')
    expect(page.getByText('item one')).toBeInTheDocument()
  })

  it('renders a figure placeholder distinctly within the preview', () => {
    const { container } = render(<DocumentPreview content="[[figure: quarterly revenue chart]]" />)
    const page = visiblePage(container)

    expect(page.getByTestId('preview-figure-placeholder')).toHaveTextContent(
      '[FIGURE PLACEHOLDER: quarterly revenue chart]',
    )
  })
})
