import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { strings } from './strings'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

describe('App', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8010')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('renders both the chat panel and the document panel', () => {
    vi.stubGlobal('fetch', vi.fn())
    render(<App />)
    expect(screen.getByLabelText(strings.chatPanelTitle)).toBeInTheDocument()
    expect(screen.getByLabelText(strings.documentPanelTitle)).toBeInTheDocument()
  })

  it('starts with empty chat and document state', () => {
    vi.stubGlobal('fetch', vi.fn())
    render(<App />)
    expect(screen.getByText(strings.chatEmpty)).toBeInTheDocument()
    expect(screen.getByText(strings.documentEmpty)).toBeInTheDocument()
  })

  it('resets to empty state when starting a new project', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }, true, 201),
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    const button = screen.getByRole('button', { name: strings.newProjectButton })
    fireEvent.click(button)
    expect(await screen.findByText(strings.chatEmpty)).toBeInTheDocument()
    expect(await screen.findByText(strings.documentEmpty)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/projects',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('sends a chat message, creates a default chapter, and shows the generated draft in the diff viewer', async () => {
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }
    const chapter = {
      id: 'c1',
      project_id: 'p1',
      title: strings.defaultChapterTitle,
      order: 0,
      created_at: 'now',
      accepted_content: null,
      pending_draft: null,
    }
    const version = {
      id: 'v1',
      chapter_id: 'c1',
      version_number: 1,
      content: 'Generated introduction text',
      created_at: 'now',
      status: 'draft' as const,
      parent_version_id: null,
    }

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(project, true, 201))
      .mockResolvedValueOnce(jsonResponse(chapter, true, 201))
      .mockResolvedValueOnce(jsonResponse(version, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: strings.newProjectButton }))
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)

    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))

    expect(await screen.findByText('Write the introduction')).toBeInTheDocument()
    expect(await screen.findByText(strings.chatDraftReadyMessage)).toBeInTheDocument()
    expect(await screen.findByText('Generated introduction text')).toBeInTheDocument()

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/projects/p1/chapters',
      expect.objectContaining({ body: JSON.stringify({ title: strings.defaultChapterTitle }) }),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/projects/p1/chapters/c1/generate',
      expect.objectContaining({ body: JSON.stringify({ instruction: 'Write the introduction' }) }),
    )
  })

  it('shows an error message in chat when generation fails', async () => {
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }
    const chapter = {
      id: 'c1',
      project_id: 'p1',
      title: strings.defaultChapterTitle,
      order: 0,
      created_at: 'now',
      accepted_content: null,
      pending_draft: null,
    }

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(project, true, 201))
      .mockResolvedValueOnce(jsonResponse(chapter, true, 201))
      .mockResolvedValueOnce(jsonResponse({ detail: 'llm failed' }, false, 502))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: strings.newProjectButton }))
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)

    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))

    expect(await screen.findByText(strings.chatGenerationErrorMessage)).toBeInTheDocument()
  })
})
