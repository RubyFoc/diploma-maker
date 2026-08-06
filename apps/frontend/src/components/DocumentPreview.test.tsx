import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DocumentPreview } from './DocumentPreview'
import { strings } from '../strings'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

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

  describe('lock selection', () => {
    beforeEach(() => {
      vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
    })

    afterEach(() => {
      vi.unstubAllEnvs()
      vi.unstubAllGlobals()
    })

    it('renders lock toggles when both chapterId and acceptedManifest are provided', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))
      const acceptedManifest = [{ id: 'b1', content: 'Some prose.', content_hash: 'h1', order: 0 }]

      const { container } = render(
        <DocumentPreview content="Some prose." chapterId="c1" acceptedManifest={acceptedManifest} />,
      )

      await waitFor(() => {
        const page = within(container.querySelector('.document-page:not(.document-page--measure)') as HTMLElement)
        expect(page.getByRole('button', { name: strings.documentBlockLockLabel })).toBeInTheDocument()
      })
    })

    it('renders no lock toggles when chapterId/acceptedManifest are omitted', () => {
      const { container } = render(<DocumentPreview content="Some prose." />)
      const page = within(container.querySelector('.document-page:not(.document-page--measure)') as HTMLElement)

      expect(page.queryByRole('button')).not.toBeInTheDocument()
    })

    it('clicking a lock toggle posts a lock for that block', async () => {
      const fetchMock = vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse(
              { id: 'l1', chapter_id: 'c1', block_id: 'b1', block_content_hash: 'h1', char_range: null, created_at: 'now' },
              true,
              201,
            ),
          )
        }
        return Promise.resolve(jsonResponse([]))
      })
      vi.stubGlobal('fetch', fetchMock)
      const acceptedManifest = [{ id: 'b1', content: 'Some prose.', content_hash: 'h1', order: 0 }]

      const { container } = render(
        <DocumentPreview content="Some prose." chapterId="c1" acceptedManifest={acceptedManifest} />,
      )
      const page = within(container.querySelector('.document-page:not(.document-page--measure)') as HTMLElement)
      fireEvent.click(await page.findByRole('button', { name: strings.documentBlockLockLabel }))

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith(
          `${BASE_URL}/chapters/c1/locks`,
          expect.objectContaining({ method: 'POST' }),
        )
      })
    })
  })

  describe('anchor selection', () => {
    beforeEach(() => {
      vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
    })

    afterEach(() => {
      vi.unstubAllEnvs()
      vi.unstubAllGlobals()
    })

    it('renders no "insert here" toggles when onSelectAnchor is omitted', () => {
      const acceptedManifest = [{ id: 'b1', content: 'Some prose.', content_hash: 'h1', order: 0 }]
      const { container } = render(
        <DocumentPreview content="Some prose." chapterId="c1" acceptedManifest={acceptedManifest} />,
      )
      const page = within(container.querySelector('.document-page:not(.document-page--measure)') as HTMLElement)

      expect(page.queryByRole('button', { name: strings.documentBlockInsertHereLabel })).not.toBeInTheDocument()
    })

    it('calls onSelectAnchor with the block id when its "insert here" toggle is clicked', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))
      const acceptedManifest = [{ id: 'b1', content: 'Some prose.', content_hash: 'h1', order: 0 }]
      const onSelectAnchor = vi.fn()

      const { container } = render(
        <DocumentPreview
          content="Some prose."
          chapterId="c1"
          acceptedManifest={acceptedManifest}
          selectedAnchorBlockId={null}
          onSelectAnchor={onSelectAnchor}
        />,
      )
      const page = within(container.querySelector('.document-page:not(.document-page--measure)') as HTMLElement)

      fireEvent.click(await page.findByRole('button', { name: strings.documentBlockInsertHereLabel }))

      expect(onSelectAnchor).toHaveBeenCalledWith('b1')
    })

    it('clicking the already-selected block clears the selection', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))
      const acceptedManifest = [{ id: 'b1', content: 'Some prose.', content_hash: 'h1', order: 0 }]
      const onSelectAnchor = vi.fn()

      const { container } = render(
        <DocumentPreview
          content="Some prose."
          chapterId="c1"
          acceptedManifest={acceptedManifest}
          selectedAnchorBlockId="b1"
          onSelectAnchor={onSelectAnchor}
        />,
      )
      const page = within(container.querySelector('.document-page:not(.document-page--measure)') as HTMLElement)

      fireEvent.click(await page.findByRole('button', { name: strings.documentBlockInsertHereSelectedLabel }))

      expect(onSelectAnchor).toHaveBeenCalledWith(null)
    })
  })
})
