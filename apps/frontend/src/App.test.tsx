import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { strings } from './strings'

const BASE_URL = 'http://localhost:8010'
const ACCESS_TOKEN_STORAGE_KEY = 'diploma-maker.accessToken'
const institution = { institution_id: 'inst-1', institution_name: 'Test University' }

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

/**
 * Builds a fetch mock that resolves the onboarding gate's institution-list call from
 * `institutions`, and otherwise dispatches responses from `queued` in call order —
 * matching this codebase's existing per-test mockResolvedValueOnce style for the
 * project/chapter/generate calls exercised once onboarding is past.
 */
function createFetchMock(queued: Response[] = []) {
  const queue = [...queued]
  return vi.fn((url: string) => {
    if (String(url).includes('/formatting/institution-configs')) {
      return Promise.resolve(jsonResponse([institution]))
    }
    const next = queue.shift()
    return Promise.resolve(next ?? jsonResponse({ detail: 'unexpected request' }, false, 500))
  })
}

/** Selects the seeded institution to move past the onboarding gate's step 2. */
async function selectInstitution() {
  const select = await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)
  fireEvent.change(select, { target: { value: institution.institution_id } })
}

describe('App', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('shows the onboarding gate when there is no access token', () => {
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn())
    render(<App />)
    expect(screen.getByLabelText(strings.onboardingTitle)).toBeInTheDocument()
  })

  it('shows the institution-selection step once a token exists', async () => {
    vi.stubGlobal('fetch', createFetchMock())
    render(<App />)
    expect(await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)).toBeInTheDocument()
  })

  it('renders both the chat panel and the document panel once onboarding is complete', async () => {
    vi.stubGlobal('fetch', createFetchMock())
    render(<App />)
    await selectInstitution()
    expect(await screen.findByLabelText(strings.chatPanelTitle)).toBeInTheDocument()
    expect(screen.getByLabelText(strings.documentPanelTitle)).toBeInTheDocument()
  })

  it('starts with empty chat and document state', async () => {
    vi.stubGlobal('fetch', createFetchMock())
    render(<App />)
    await selectInstitution()
    expect(await screen.findByText(strings.chatEmpty)).toBeInTheDocument()
    expect(screen.getByText(strings.documentEmpty)).toBeInTheDocument()
  })

  it('resets to empty state when starting a new project', async () => {
    const fetchMock = createFetchMock([
      jsonResponse({ id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }, true, 201),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await selectInstitution()
    const button = await screen.findByRole('button', { name: strings.newProjectButton })
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

    const generateResponse = {
      version,
      precheck: { plagiarism_score: 0, ai_fingerprint_score: 0, flagged: false, reasons: [] },
    }

    const fetchMock = createFetchMock([
      jsonResponse(project, true, 201),
      jsonResponse(chapter, true, 201),
      jsonResponse(generateResponse, true, 201),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await selectInstitution()
    fireEvent.click(await screen.findByRole('button', { name: strings.newProjectButton }))
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

    const fetchMock = createFetchMock([
      jsonResponse(project, true, 201),
      jsonResponse(chapter, true, 201),
      jsonResponse({ detail: 'llm failed' }, false, 502),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await selectInstitution()
    fireEvent.click(await screen.findByRole('button', { name: strings.newProjectButton }))
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)

    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))

    expect(await screen.findByText(strings.chatGenerationErrorMessage)).toBeInTheDocument()
  })

  it('accepting a draft records an approve feedback signal and refreshes the project', async () => {
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
    const generateResponse = {
      version,
      precheck: { plagiarism_score: 0, ai_fingerprint_score: 0, flagged: false, reasons: [] },
    }
    const acceptedVersion = { ...version, status: 'accepted' as const }
    const signal = {
      id: 's1',
      institution_id: institution.institution_id,
      chapter_id: 'c1',
      version_id: 'v1',
      signal_type: 'approve' as const,
      created_at: 'now',
    }
    const refreshedProject = {
      ...project,
      chapters: [{ ...chapter, accepted_content: 'Generated introduction text', pending_draft: null }],
    }

    const fetchMock = createFetchMock([
      jsonResponse(project, true, 201),
      jsonResponse(chapter, true, 201),
      jsonResponse(generateResponse, true, 201),
      jsonResponse(acceptedVersion),
      jsonResponse(signal, true, 201),
      jsonResponse(refreshedProject),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await selectInstitution()
    fireEvent.click(await screen.findByRole('button', { name: strings.newProjectButton }))
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)
    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))
    await screen.findByText('Generated introduction text')

    fireEvent.click(screen.getByRole('button', { name: strings.diffAcceptButton }))

    await waitFor(() => {
      expect(screen.queryByLabelText(strings.diffViewerTitle)).not.toBeInTheDocument()
    })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/versions/v1/accept',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/feedback/signals',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          institution_id: institution.institution_id,
          chapter_id: 'c1',
          version_id: 'v1',
          signal_type: 'approve',
        }),
      }),
    )
  })

  it('still completes the accept flow when recording the feedback signal fails', async () => {
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
    const generateResponse = {
      version,
      precheck: { plagiarism_score: 0, ai_fingerprint_score: 0, flagged: false, reasons: [] },
    }
    const acceptedVersion = { ...version, status: 'accepted' as const }
    const refreshedProject = {
      ...project,
      chapters: [{ ...chapter, accepted_content: 'Generated introduction text', pending_draft: null }],
    }

    const fetchMock = createFetchMock([
      jsonResponse(project, true, 201),
      jsonResponse(chapter, true, 201),
      jsonResponse(generateResponse, true, 201),
      jsonResponse(acceptedVersion),
      jsonResponse({ detail: 'feedback service down' }, false, 500),
      jsonResponse(refreshedProject),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await selectInstitution()
    fireEvent.click(await screen.findByRole('button', { name: strings.newProjectButton }))
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)
    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))
    await screen.findByText('Generated introduction text')

    fireEvent.click(screen.getByRole('button', { name: strings.diffAcceptButton }))

    await waitFor(() => {
      expect(screen.queryByLabelText(strings.diffViewerTitle)).not.toBeInTheDocument()
    })
    expect(screen.getByText('Generated introduction text')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/versions/v1/accept',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('rejecting a draft records a reject feedback signal and clears the pending draft', async () => {
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
    const generateResponse = {
      version,
      precheck: { plagiarism_score: 0, ai_fingerprint_score: 0, flagged: false, reasons: [] },
    }
    const signal = {
      id: 's2',
      institution_id: institution.institution_id,
      chapter_id: 'c1',
      version_id: 'v1',
      signal_type: 'reject' as const,
      created_at: 'now',
    }

    const fetchMock = createFetchMock([
      jsonResponse(project, true, 201),
      jsonResponse(chapter, true, 201),
      jsonResponse(generateResponse, true, 201),
      jsonResponse(signal, true, 201),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await selectInstitution()
    fireEvent.click(await screen.findByRole('button', { name: strings.newProjectButton }))
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)
    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))
    await screen.findByText('Generated introduction text')

    fireEvent.click(screen.getByRole('button', { name: strings.diffRejectButton }))

    await waitFor(() => {
      expect(screen.queryByLabelText(strings.diffViewerTitle)).not.toBeInTheDocument()
    })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/feedback/signals',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          institution_id: institution.institution_id,
          chapter_id: 'c1',
          version_id: 'v1',
          signal_type: 'reject',
        }),
      }),
    )
  })
})
