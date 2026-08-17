import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

type Listener = (event: { type: string; data?: string }) => void

/**
 * Minimal `EventSource` stand-in (jsdom has no native one) for exercising `ChatPanel`'s
 * SSE-based generation flow (ADR-0009/TASK-E08-3), replacing the old fetch-mocked `/generate`
 * response in these tests. `MockEventSource.instances` lets a test grab the most recently
 * constructed stream and drive it with `dispatch`.
 */
class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  closed = false
  private listeners: Record<string, Listener[]> = {}

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners[type] = [...(this.listeners[type] ?? []), listener]
  }

  close() {
    this.closed = true
  }

  dispatch(type: string, data?: string) {
    for (const listener of this.listeners[type] ?? []) {
      listener({ type, data })
    }
  }
}

/**
 * `PaginatedDocument` (TASK-E10-4) renders an off-screen, `aria-hidden` measuring pass
 * alongside the visible page — both contain the same chapter text — so a plain
 * `findByText` would match twice once a chapter has content. Waits for the text to
 * appear, then returns only the copy outside the hidden measuring pass.
 */
async function findVisibleByText(text: string): Promise<HTMLElement> {
  const matches = await screen.findAllByText(text)
  const visible = matches.find((element) => !element.closest('.document-page--measure'))
  if (!visible) {
    throw new Error(`no visible (non-measuring-pass) match found for "${text}"`)
  }
  return visible
}

function latestEventSource(): MockEventSource {
  const source = MockEventSource.instances[MockEventSource.instances.length - 1]
  if (!source) {
    throw new Error('no EventSource was constructed')
  }
  return source
}

/**
 * Builds a fetch mock that resolves the new-project setup UI's institution-list call from
 * `institutions`, and otherwise dispatches responses from `queued` in call order —
 * matching this codebase's existing per-test mockResolvedValueOnce style for the
 * project/chapter/generate calls exercised once a project is created.
 */
function createFetchMock(queued: Response[] = []) {
  const queue = [...queued]
  return vi.fn((url: string, init?: RequestInit) => {
    if (String(url).endsWith('/formatting/institution-configs')) {
      return Promise.resolve(jsonResponse([institution]))
    }
    // `useInstitutionConfig` fetches `/formatting/institution-configs/{id}` once a project's
    // institution is set, independently of the queued project/chapter/version responses below
    // — respond with a 404 (swallowed to a null config) rather than consuming a queue slot,
    // so it doesn't desync the ordering the other tests assert on.
    if (String(url).includes('/formatting/institution-configs/')) {
      return Promise.resolve(jsonResponse({ detail: 'not found' }, false, 404))
    }
    // The project landing view lists projects on mount (`GET /projects`) before any test's own
    // create/open flow runs — respond with an empty list rather than consuming a queue slot, for
    // the same reason as institution-configs above.
    if (String(url).endsWith('/projects') && (!init?.method || init.method === 'GET')) {
      return Promise.resolve(jsonResponse([]))
    }
    // `useChapterLocks` (TASK-E13-5) fetches `/chapters/{id}/locks` independently of the queued
    // responses below whenever `DocumentPreview` renders a chapter's accepted content — respond
    // with an empty lock list rather than consuming a queue slot, same reasoning as
    // institution-configs/projects above.
    if (/\/chapters\/.+\/locks$/.test(String(url)) && (!init?.method || init.method === 'GET')) {
      return Promise.resolve(jsonResponse([]))
    }
    // `useChapterHistory` (TASK-E16-5) fetches `/chapters/{id}/operations` whenever a chapter has
    // a pending draft — respond with the zeroed "no history yet" shape rather than consuming a
    // queue slot, same reasoning as institution-configs/projects/locks above.
    if (/\/chapters\/.+\/operations$/.test(String(url)) && (!init?.method || init.method === 'GET')) {
      return Promise.resolve(jsonResponse({ operations: [], applied_count: 0, total_operations: 0 }))
    }
    const next = queue.shift()
    return Promise.resolve(next ?? jsonResponse({ detail: 'unexpected request' }, false, 500))
  })
}

/** Opens the "create new project" setup UI from the project-landing view. */
async function openNewProjectSetup() {
  fireEvent.click(await screen.findByRole('button', { name: strings.newProjectButton }))
  await screen.findByLabelText(strings.newProjectSetupTitle)
}

/** Selects the seeded institution within the new-project setup UI. */
async function selectInstitution() {
  const select = await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)
  fireEvent.change(select, { target: { value: institution.institution_id } })
}

/** Submits the new-project setup UI, creating the project. */
async function submitNewProjectSetup() {
  fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupCreateButton }))
}

/**
 * Moves past the new project-landing view (shown before any project is active) by opening
 * "New Project" and submitting the setup UI without picking an institution, landing the caller
 * in the chat+preview workspace. Callers that need a created project in their fetch queue (e.g.
 * to assert on chapter/generate calls) must include that project response as the *first* queued
 * response.
 */
async function enterWorkspace() {
  await openNewProjectSetup()
  await submitNewProjectSetup()
  await screen.findByLabelText(strings.chatPanelTitle)
}

/** Same as `enterWorkspace`, but picks the seeded institution before submitting. */
async function enterWorkspaceWithInstitution() {
  await openNewProjectSetup()
  await selectInstitution()
  await submitNewProjectSetup()
  await screen.findByLabelText(strings.chatPanelTitle)
}

describe('App', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'test-token')
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
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

  it('shows the project landing view (not the chat panel or an institution gate) once a token exists', async () => {
    vi.stubGlobal('fetch', createFetchMock())
    render(<App />)
    expect(await screen.findByLabelText(strings.projectLandingTitle)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: strings.newProjectButton })).toBeInTheDocument()
    expect(screen.queryByLabelText(strings.chatPanelTitle)).not.toBeInTheDocument()
  })

  it('shows the new-project setup UI (university select/upload/auto-detect + required sources) after clicking New Project', async () => {
    vi.stubGlobal('fetch', createFetchMock())
    render(<App />)
    await openNewProjectSetup()
    expect(screen.getByLabelText(strings.newProjectSetupInstitutionSelectLabel)).toBeInTheDocument()
  })

  it('renders both the chat panel and the document panel once a project is entered', async () => {
    const fetchMock = createFetchMock([
      jsonResponse({ id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }, true, 201),
    ])
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await enterWorkspace()
    expect(await screen.findByLabelText(strings.chatPanelTitle)).toBeInTheDocument()
    expect(screen.getByLabelText(strings.documentPanelTitle)).toBeInTheDocument()
  })

  it('"My Projects" returns to the landing view without losing the active document state', async () => {
    let projectCreated = false
    const projectDetail = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (String(url).endsWith('/formatting/institution-configs')) {
        return Promise.resolve(jsonResponse([institution]))
      }
      if (String(url).includes('/formatting/institution-configs/')) {
        return Promise.resolve(jsonResponse({ detail: 'not found' }, false, 404))
      }
      if (String(url).endsWith('/projects') && init?.method === 'POST') {
        projectCreated = true
        return Promise.resolve(jsonResponse(projectDetail, true, 201))
      }
      if (String(url).endsWith('/projects')) {
        return Promise.resolve(
          jsonResponse(projectCreated ? [{ id: 'p1', title: 'Untitled', created_at: 'now' }] : []),
        )
      }
      if (String(url).endsWith('/projects/p1')) {
        return Promise.resolve(jsonResponse(projectDetail))
      }
      return Promise.resolve(jsonResponse({ detail: 'unexpected request' }, false, 500))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await enterWorkspace()

    // Send a chat message so there is in-progress state (chat history + a chapter) living in
    // context, outside of ChatPanel/Workspace's own component-local state.
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)
    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))
    expect(await screen.findByText('Write the introduction')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: strings.myProjectsButton }))
    expect(await screen.findByLabelText(strings.projectLandingTitle)).toBeInTheDocument()
    expect(screen.queryByLabelText(strings.chatPanelTitle)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: strings.projectLandingOpenButton }))
    expect(await screen.findByLabelText(strings.chatPanelTitle)).toBeInTheDocument()
    expect(await screen.findByText('Write the introduction')).toBeInTheDocument()
  })

  it('logging out returns to onboarding and clears the stored access token', async () => {
    const fetchMock = createFetchMock([
      jsonResponse({ id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }, true, 201),
    ])
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await enterWorkspace()
    expect(await screen.findByLabelText(strings.chatPanelTitle)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: strings.logoutButton }))

    expect(await screen.findByLabelText(strings.onboardingTitle)).toBeInTheDocument()
    expect(localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('starts with empty chat and document state', async () => {
    const fetchMock = createFetchMock([
      jsonResponse({ id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }, true, 201),
    ])
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await enterWorkspace()
    expect(await screen.findByText(strings.chatEmpty)).toBeInTheDocument()
    expect(screen.getByText(strings.documentEmpty)).toBeInTheDocument()
  })

  it('resets to empty state when starting a new project', async () => {
    const fetchMock = createFetchMock([
      jsonResponse({ id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }, true, 201),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await enterWorkspaceWithInstitution()
    expect(await screen.findByText(strings.chatEmpty)).toBeInTheDocument()
    expect(await screen.findByText(strings.documentEmpty)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/projects',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('uploading a whole document replaces the empty-chapters message with the created chapters', async () => {
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }
    const projectWithChapters = {
      ...project,
      chapters: [
        {
          id: 'c1',
          project_id: 'p1',
          parent_chapter_id: null,
          title: 'Introduction',
          order: 0,
          created_at: 'now',
          accepted_content: null,
          accepted_manifest: null,
          pending_draft: {
            id: 'v1',
            chapter_id: 'c1',
            version_number: 1,
            content: 'Some body text.',
            manifest: null,
            created_at: 'now',
            status: 'draft',
            parent_version_id: null,
          },
        },
      ],
    }
    const fetchMock = createFetchMock([jsonResponse(project, true, 201), jsonResponse(projectWithChapters, true, 201)])
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await enterWorkspace()
    expect(await screen.findByText(strings.documentEmpty)).toBeInTheDocument()

    const file = new File(['thesis'], 'thesis.docx')
    fireEvent.change(screen.getByLabelText(strings.documentUploadLabel), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: strings.documentUploadButton }))

    await findVisibleByText('Introduction')
    expect(screen.queryByText(strings.documentEmpty)).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/projects/p1/document/upload',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('shows an error message when the whole-document upload fails', async () => {
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }
    const fetchMock = createFetchMock([
      jsonResponse(project, true, 201),
      jsonResponse({ detail: 'Could not find any Heading 1 paragraphs' }, false, 422),
    ])
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await enterWorkspace()

    const file = new File(['thesis'], 'thesis.docx')
    fireEvent.change(screen.getByLabelText(strings.documentUploadLabel), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: strings.documentUploadButton }))

    expect(await screen.findByText(strings.documentUploadErrorMessage)).toBeInTheDocument()
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

    const fetchMock = createFetchMock([jsonResponse(project, true, 201), jsonResponse(chapter, true, 201)])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await enterWorkspaceWithInstitution()
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)

    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))

    expect(await screen.findByText('Write the introduction')).toBeInTheDocument()

    const source = await waitFor(() => latestEventSource())
    expect(source.url).toBe(
      'http://localhost:8010/projects/p1/chapters/c1/generate/stream?instruction=Write+the+introduction',
    )
    act(() => {
      source.dispatch('token', 'Generated ')
      source.dispatch('done', JSON.stringify(generateResponse))
    })

    expect(await screen.findByText(strings.chatDraftReadyMessage)).toBeInTheDocument()
    expect(await findVisibleByText('Generated introduction text')).toBeInTheDocument()

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/projects/p1/chapters',
      expect.objectContaining({ body: JSON.stringify({ title: strings.defaultChapterTitle }) }),
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

    const fetchMock = createFetchMock([jsonResponse(project, true, 201), jsonResponse(chapter, true, 201)])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await enterWorkspaceWithInstitution()
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)

    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))

    const source = await waitFor(() => latestEventSource())
    act(() => {
      source.dispatch('error', JSON.stringify({ detail: 'llm failed' }))
    })

    expect(await screen.findByText(strings.chatGenerationErrorMessage)).toBeInTheDocument()
  })

  it('accepting a draft records an approve feedback signal and refreshes the project', async () => {
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [], institution_id: institution.institution_id }
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
      jsonResponse(project), // title-sync refetch fired after generation's `done` event
      jsonResponse(acceptedVersion),
      jsonResponse(signal, true, 201),
      jsonResponse(refreshedProject),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await enterWorkspaceWithInstitution()
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)
    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))
    const source = await waitFor(() => latestEventSource())
    act(() => {
      source.dispatch('done', JSON.stringify(generateResponse))
    })
    await findVisibleByText('Generated introduction text')

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
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [], institution_id: institution.institution_id }
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
      jsonResponse(project), // title-sync refetch fired after generation's `done` event
      jsonResponse(acceptedVersion),
      jsonResponse({ detail: 'feedback service down' }, false, 500),
      jsonResponse(refreshedProject),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await enterWorkspaceWithInstitution()
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)
    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))
    const source = await waitFor(() => latestEventSource())
    act(() => {
      source.dispatch('done', JSON.stringify(generateResponse))
    })
    await findVisibleByText('Generated introduction text')

    fireEvent.click(screen.getByRole('button', { name: strings.diffAcceptButton }))

    await waitFor(() => {
      expect(screen.queryByLabelText(strings.diffViewerTitle)).not.toBeInTheDocument()
    })
    expect(await findVisibleByText('Generated introduction text')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8010/versions/v1/accept',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('selecting an "insert here" block sends generateChapterDraft with target_block_id instead of streaming, and surfaces a reroute banner', async () => {
    const chapter = {
      id: 'c1',
      project_id: 'p1',
      parent_chapter_id: null,
      title: 'Chapter 1',
      order: 0,
      created_at: 'now',
      accepted_content: 'Existing paragraph.',
      accepted_manifest: [{ id: 'b1', content: 'Existing paragraph.', content_hash: 'h1', order: 0 }],
      pending_draft: null,
    }
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [chapter] }
    const anchorVersion = {
      id: 'v2',
      chapter_id: 'c1',
      version_number: 2,
      content: 'Existing paragraph.\nInserted sentence.',
      created_at: 'now',
      status: 'draft' as const,
      parent_version_id: null,
    }
    const generateResponse = {
      version: anchorVersion,
      precheck: { plagiarism_score: 0, ai_fingerprint_score: 0, flagged: false, reasons: [] },
      unmet_required_sources: [],
      used_block_id: 'b2',
      rerouted_from_block_id: 'b1',
    }

    const fetchMock = createFetchMock([
      jsonResponse(project, true, 201),
      jsonResponse(generateResponse, true, 201),
      jsonResponse(project), // title-sync refetch fired after the generate call resolves
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await enterWorkspace()

    fireEvent.click(await screen.findByRole('button', { name: strings.documentBlockInsertHereLabel }))
    expect(await screen.findByText(strings.chatInsertingAtIndicator)).toBeInTheDocument()

    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)
    fireEvent.change(input, { target: { value: 'Insert a sentence here' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8010/projects/p1/chapters/c1/generate',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ instruction: 'Insert a sentence here', target_block_id: 'b1' }),
        }),
      )
    })
    // No SSE stream was opened for anchor-mode generation (TASK-E15-3 scope: anchor mode only
    // goes through the non-streaming `generateChapterDraft`).
    expect(MockEventSource.instances).toHaveLength(0)

    expect(await screen.findByText(strings.diffRerouteNoticeMessage)).toBeInTheDocument()
    // The anchor selection indicator clears once generation starts.
    expect(screen.queryByText(strings.chatInsertingAtIndicator)).not.toBeInTheDocument()
  })

  it('only offers the "insert here" toggle on the first chapter, since chat generation always targets chapters[0]', async () => {
    const firstChapter = {
      id: 'c1',
      project_id: 'p1',
      parent_chapter_id: null,
      title: 'Chapter 1',
      order: 0,
      created_at: 'now',
      accepted_content: 'First chapter paragraph.',
      accepted_manifest: [{ id: 'b1', content: 'First chapter paragraph.', content_hash: 'h1', order: 0 }],
      pending_draft: null,
    }
    const secondChapter = {
      id: 'c2',
      project_id: 'p1',
      parent_chapter_id: null,
      title: 'Chapter 2',
      order: 1,
      created_at: 'now',
      accepted_content: 'Second chapter paragraph.',
      accepted_manifest: [{ id: 'b2', content: 'Second chapter paragraph.', content_hash: 'h2', order: 0 }],
      pending_draft: null,
    }
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [firstChapter, secondChapter] }

    vi.stubGlobal('fetch', createFetchMock([jsonResponse(project, true, 201)]))

    render(<App />)
    await enterWorkspace()

    await findVisibleByText('First chapter paragraph.')
    await findVisibleByText('Second chapter paragraph.')

    expect(await screen.findAllByRole('button', { name: strings.documentBlockInsertHereLabel })).toHaveLength(1)
  })

  it('shows a distinct message when anchor-mode generation fails because the chapter is fully locked (409)', async () => {
    const chapter = {
      id: 'c1',
      project_id: 'p1',
      parent_chapter_id: null,
      title: 'Chapter 1',
      order: 0,
      created_at: 'now',
      accepted_content: 'Existing paragraph.',
      accepted_manifest: [{ id: 'b1', content: 'Existing paragraph.', content_hash: 'h1', order: 0 }],
      pending_draft: null,
    }
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [chapter] }

    const fetchMock = createFetchMock([
      jsonResponse(project, true, 201),
      jsonResponse({ detail: 'chapter fully locked' }, false, 409),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await enterWorkspace()

    fireEvent.click(await screen.findByRole('button', { name: strings.documentBlockInsertHereLabel }))
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)
    fireEvent.change(input, { target: { value: 'Insert a sentence here' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))

    expect(await screen.findByText(strings.chatChapterFullyLockedMessage)).toBeInTheDocument()
    expect(screen.queryByText(strings.chatGenerationErrorMessage)).not.toBeInTheDocument()
  })

  it('rejecting a draft records a reject feedback signal and clears the pending draft', async () => {
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [], institution_id: institution.institution_id }
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
      jsonResponse(signal, true, 201),
    ])
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await enterWorkspaceWithInstitution()
    const input = await screen.findByPlaceholderText(strings.chatInputPlaceholder)
    fireEvent.change(input, { target: { value: 'Write the introduction' } })
    fireEvent.click(screen.getByRole('button', { name: strings.chatSendButton }))
    const source = await waitFor(() => latestEventSource())
    act(() => {
      source.dispatch('done', JSON.stringify(generateResponse))
    })
    await findVisibleByText('Generated introduction text')

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
