import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderMarkdownPreview } from './renderMarkdownPreview'

describe('renderMarkdownPreview', () => {
  it('renders #/##/### headings as h1/h2/h3', () => {
    render(<>{renderMarkdownPreview('# Title\n\n## Section\n\n### Subsection')}</>)

    expect(screen.getByRole('heading', { level: 1, name: 'Title' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Section' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'Subsection' })).toBeInTheDocument()
  })

  it('renders bold and italic inline markup as strong/em', () => {
    render(<>{renderMarkdownPreview('This is **bold** and this is *italic*.')}</>)

    const strong = screen.getByText('bold')
    const em = screen.getByText('italic')
    expect(strong.tagName).toBe('STRONG')
    expect(em.tagName).toBe('EM')
  })

  it('renders unordered lists as ul/li', () => {
    render(<>{renderMarkdownPreview('- first item\n- second item')}</>)

    const list = screen.getByRole('list')
    expect(list.tagName).toBe('UL')
    expect(screen.getByText('first item')).toBeInTheDocument()
    expect(screen.getByText('second item')).toBeInTheDocument()
  })

  it('renders ordered lists as ol/li', () => {
    render(<>{renderMarkdownPreview('1. first item\n2. second item')}</>)

    const list = screen.getByRole('list')
    expect(list.tagName).toBe('OL')
    expect(screen.getByText('first item')).toBeInTheDocument()
    expect(screen.getByText('second item')).toBeInTheDocument()
  })

  it('renders a figure placeholder as a distinctly-marked element with the description visible', () => {
    render(<>{renderMarkdownPreview('[[figure: bar chart comparing revenue]]')}</>)

    const placeholder = screen.getByTestId('preview-figure-placeholder')
    expect(placeholder).toHaveTextContent('[FIGURE PLACEHOLDER: bar chart comparing revenue]')
  })

  it('renders unsupported constructs (blockquote) as visible plain text rather than dropping them', () => {
    render(<>{renderMarkdownPreview('> a quoted line')}</>)

    expect(screen.getByText('> a quoted line')).toBeInTheDocument()
  })

  it('renders unsupported constructs (table-like line) as visible plain text rather than dropping them', () => {
    render(<>{renderMarkdownPreview('| col1 | col2 |')}</>)

    expect(screen.getByText('| col1 | col2 |')).toBeInTheDocument()
  })
})
