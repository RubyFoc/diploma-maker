import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DocumentPreview } from './DocumentPreview'
import { strings } from '../strings'

describe('DocumentPreview', () => {
  it('renders the empty-state string when content is empty', () => {
    render(<DocumentPreview content="" />)

    expect(screen.getByText(strings.chapterContentEmpty)).toBeInTheDocument()
  })

  it('renders formatted Markdown content as headings, paragraphs, and lists', () => {
    render(<DocumentPreview content={'# Chapter One\n\nSome **bold** prose.\n\n- item one\n- item two'} />)

    expect(screen.getByRole('heading', { level: 1, name: 'Chapter One' })).toBeInTheDocument()
    expect(screen.getByText('bold').tagName).toBe('STRONG')
    expect(screen.getByRole('list').tagName).toBe('UL')
    expect(screen.getByText('item one')).toBeInTheDocument()
  })

  it('renders a figure placeholder distinctly within the preview', () => {
    render(<DocumentPreview content="[[figure: quarterly revenue chart]]" />)

    expect(screen.getByTestId('preview-figure-placeholder')).toHaveTextContent(
      '[FIGURE PLACEHOLDER: quarterly revenue chart]',
    )
  })
})
