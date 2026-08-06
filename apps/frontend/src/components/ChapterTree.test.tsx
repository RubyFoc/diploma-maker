import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ChapterTree } from './ChapterTree'
import { strings } from '../strings'
import type { ChapterDetail } from '../types/project'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

function chapter(id: string, title: string, order = 0): ChapterDetail {
  return {
    id,
    project_id: 'p1',
    parent_chapter_id: null,
    title,
    order,
    created_at: 'now',
    accepted_content: null,
    pending_draft: null,
  }
}

function subchapter(id: string, title: string, parentId: string, order = 0): ChapterDetail {
  return { ...chapter(id, title, order), parent_chapter_id: parentId }
}

describe('ChapterTree', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('shows an empty-state message when there are no chapters', async () => {
    vi.stubGlobal('fetch', vi.fn())

    render(<ChapterTree projectId="p1" chapters={[]} selectedChapterId={null} onSelectChapter={vi.fn()} />)

    expect(screen.getByText(strings.chapterTreeEmpty)).toBeInTheDocument()
  })

  it('lists top-level chapters and fetches subchapters for each', async () => {
    const chapters = [chapter('c1', 'Chapter 1'), chapter('c2', 'Chapter 2', 1)]
    const fetchMock = vi.fn((url: string) => {
      if (String(url).endsWith('/chapters/c1/subchapters')) {
        return Promise.resolve(jsonResponse([subchapter('s1', 'Section 1.1', 'c1')]))
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ChapterTree projectId="p1" chapters={chapters} selectedChapterId={null} onSelectChapter={vi.fn()} />)

    expect(await screen.findByText('Chapter 1')).toBeInTheDocument()
    expect(screen.getByText('Chapter 2')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/projects/p1/chapters/c1/subchapters`, expect.anything())
    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/projects/p1/chapters/c2/subchapters`, expect.anything())
  })

  it('expanding a chapter with subchapters reveals them, collapsing hides them again', async () => {
    const chapters = [chapter('c1', 'Chapter 1')]
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse([subchapter('s1', 'Section 1.1', 'c1')])),
    )

    render(<ChapterTree projectId="p1" chapters={chapters} selectedChapterId={null} onSelectChapter={vi.fn()} />)
    await screen.findByText('Chapter 1')

    expect(screen.queryByText('Section 1.1')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: strings.chapterTreeExpandLabel }))
    expect(screen.getByText('Section 1.1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: strings.chapterTreeCollapseLabel }))
    expect(screen.queryByText('Section 1.1')).not.toBeInTheDocument()
  })

  it('clicking a chapter title calls onSelectChapter with its id', async () => {
    const chapters = [chapter('c1', 'Chapter 1')]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))
    const onSelectChapter = vi.fn()

    render(<ChapterTree projectId="p1" chapters={chapters} selectedChapterId={null} onSelectChapter={onSelectChapter} />)
    fireEvent.click(await screen.findByText('Chapter 1'))

    expect(onSelectChapter).toHaveBeenCalledWith('c1')
  })

  it('marks the selected chapter with the selected styling', async () => {
    const chapters = [chapter('c1', 'Chapter 1')]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))

    render(<ChapterTree projectId="p1" chapters={chapters} selectedChapterId="c1" onSelectChapter={vi.fn()} />)

    expect(await screen.findByText('Chapter 1')).toHaveClass('chapter-tree-item--selected')
  })

  it('adding a subchapter posts the title and shows it once expanded', async () => {
    const chapters = [chapter('c1', 'Chapter 1')]
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return Promise.resolve(jsonResponse(subchapter('s1', 'New Section', 'c1'), true, 201))
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ChapterTree projectId="p1" chapters={chapters} selectedChapterId={null} onSelectChapter={vi.fn()} />)
    await screen.findByText('Chapter 1')

    fireEvent.click(screen.getByRole('button', { name: strings.chapterTreeAddSubchapterButton }))
    fireEvent.change(screen.getByLabelText(strings.chapterTreeAddSubchapterInputLabel), {
      target: { value: 'New Section' },
    })
    fireEvent.click(screen.getByRole('button', { name: strings.chapterTreeAddSubchapterConfirmButton }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        `${BASE_URL}/projects/p1/chapters/c1/subchapters`,
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ title: 'New Section' }) }),
      )
    })
    expect(await screen.findByText('New Section')).toBeInTheDocument()
  })

  it('shows an error message when adding a subchapter fails', async () => {
    const chapters = [chapter('c1', 'Chapter 1')]
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ detail: 'server error' }, false, 500))
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ChapterTree projectId="p1" chapters={chapters} selectedChapterId={null} onSelectChapter={vi.fn()} />)
    await screen.findByText('Chapter 1')

    fireEvent.click(screen.getByRole('button', { name: strings.chapterTreeAddSubchapterButton }))
    fireEvent.change(screen.getByLabelText(strings.chapterTreeAddSubchapterInputLabel), {
      target: { value: 'New Section' },
    })
    fireEvent.click(screen.getByRole('button', { name: strings.chapterTreeAddSubchapterConfirmButton }))

    expect(await screen.findByText(strings.chapterTreeAddSubchapterErrorMessage)).toBeInTheDocument()
  })

  it('cancelling the add-subchapter form discards it without posting', async () => {
    const chapters = [chapter('c1', 'Chapter 1')]
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    render(<ChapterTree projectId="p1" chapters={chapters} selectedChapterId={null} onSelectChapter={vi.fn()} />)
    await screen.findByText('Chapter 1')

    fireEvent.click(screen.getByRole('button', { name: strings.chapterTreeAddSubchapterButton }))
    fireEvent.click(screen.getByRole('button', { name: strings.chapterTreeAddSubchapterCancelButton }))

    expect(screen.queryByLabelText(strings.chapterTreeAddSubchapterInputLabel)).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ method: 'POST' }))
  })
})
