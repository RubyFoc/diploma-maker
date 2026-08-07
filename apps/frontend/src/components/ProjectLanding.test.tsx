import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectLanding } from './ProjectLanding'
import { ChatProvider, useChat } from '../context/ChatContext'
import { DocumentProvider, useDocument } from '../context/DocumentContext'
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

/** Surfaces `DocumentContext`/`ChatContext` state in the DOM so tests can assert on it. */
function StateProbe() {
  const { document: doc } = useDocument()
  const { chat } = useChat()
  return (
    <div data-testid="state-probe" data-project-id={doc.projectId ?? ''} data-chat-length={chat.messages.length} />
  )
}

function renderLanding(onProjectActivated = vi.fn()) {
  const utils = render(
    <DocumentProvider>
      <ChatProvider>
        <ProjectLanding onProjectActivated={onProjectActivated} />
        <StateProbe />
      </ChatProvider>
    </DocumentProvider>,
  )
  return { ...utils, onProjectActivated }
}

describe('ProjectLanding', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('shows the heading and New Project button, and lists projects (title and created date)', async () => {
    const projects = [
      { id: 'p1', title: 'My Thesis', created_at: '2026-01-15T00:00:00Z' },
      { id: 'p2', title: 'Other Thesis', created_at: '2026-02-20T00:00:00Z' },
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(projects)))

    renderLanding()

    expect(screen.getByLabelText(strings.projectLandingTitle)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: strings.newProjectButton })).toBeInTheDocument()

    const panel = await screen.findByLabelText(strings.projectLandingTitle)
    expect(within(panel).getByText('My Thesis')).toBeInTheDocument()
    expect(within(panel).getByText('Other Thesis')).toBeInTheDocument()
  })

  it('shows an empty-state message when the caller has no projects', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))

    renderLanding()

    expect(await screen.findByText(strings.projectLandingEmpty)).toBeInTheDocument()
  })

  it('shows an error message when the project list fails to load', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'server error' }, false, 500)))

    renderLanding()

    expect(await screen.findByText(strings.projectLandingLoadErrorMessage)).toBeInTheDocument()
  })

  it('clicking New Project opens the setup UI, and submitting it creates the project and calls onProjectActivated', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (String(url).includes('/formatting/institution-configs')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (String(url).endsWith('/projects')) {
        return Promise.resolve(jsonResponse({ id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }, true, 201))
      }
      return Promise.resolve(jsonResponse({ detail: 'unexpected request' }, false, 500))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { onProjectActivated } = renderLanding()
    fireEvent.click(await screen.findByRole('button', { name: strings.newProjectButton }))

    expect(await screen.findByLabelText(strings.newProjectSetupTitle)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupCreateButton }))

    await waitFor(() => {
      expect(onProjectActivated).toHaveBeenCalled()
    })
  })

  it('cancelling the new-project setup UI returns to the project list without creating a project', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))

    renderLanding()
    fireEvent.click(await screen.findByRole('button', { name: strings.newProjectButton }))
    expect(await screen.findByLabelText(strings.newProjectSetupTitle)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupCancelButton }))

    expect(await screen.findByLabelText(strings.projectLandingTitle)).toBeInTheDocument()
  })

  it('cancelling after adding a required source discards it, so it does not resurface on the next New Project attempt', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))

    renderLanding()
    fireEvent.click(await screen.findByRole('button', { name: strings.newProjectButton }))
    expect(await screen.findByLabelText(strings.newProjectSetupTitle)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(strings.newProjectSetupRequiredSourceAuthorLabel), {
      target: { value: 'Jane Doe' },
    })
    fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupRequiredSourceAddButton }))
    expect(await screen.findByText('Jane Doe')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupCancelButton }))
    expect(await screen.findByLabelText(strings.projectLandingTitle)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: strings.newProjectButton }))
    expect(await screen.findByLabelText(strings.newProjectSetupTitle)).toBeInTheDocument()
    expect(screen.queryByText('Jane Doe')).not.toBeInTheDocument()
  })

  it('switching to a project fetches its detail, updates active document/chat state, and calls onProjectActivated', async () => {
    const projects = [{ id: 'p1', title: 'My Thesis', created_at: '2026-01-15T00:00:00Z' }]
    const projectDetail = { id: 'p1', title: 'My Thesis', created_at: '2026-01-15T00:00:00Z', chapters: [] }
    const fetchMock = vi.fn((url: string) => {
      if (String(url).endsWith('/projects')) {
        return Promise.resolve(jsonResponse(projects))
      }
      return Promise.resolve(jsonResponse(projectDetail))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { onProjectActivated } = renderLanding()
    await screen.findByText('My Thesis')

    fireEvent.click(screen.getByRole('button', { name: strings.projectLandingOpenButton }))

    await waitFor(() => {
      expect(screen.getByTestId('state-probe')).toHaveAttribute('data-project-id', 'p1')
    })
    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/projects/p1`, expect.anything())
    expect(onProjectActivated).toHaveBeenCalled()
  })

  it('deleting a project requires confirmation before calling deleteProject', async () => {
    const projects = [{ id: 'p1', title: 'My Thesis', created_at: '2026-01-15T00:00:00Z' }]
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        return Promise.resolve({ ok: true, status: 204, json: () => Promise.reject(new Error('no body')), text: () => Promise.resolve('') } as unknown as Response)
      }
      return Promise.resolve(jsonResponse(projects))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderLanding()
    await screen.findByText('My Thesis')

    fireEvent.click(screen.getByRole('button', { name: strings.projectLandingDeleteButton }))
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining('/projects/p1'), expect.objectContaining({ method: 'DELETE' }))

    fireEvent.click(screen.getByRole('button', { name: strings.projectLandingDeleteConfirmButton }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/projects/p1`, expect.objectContaining({ method: 'DELETE' }))
    })
    await waitFor(() => {
      expect(screen.queryByText('My Thesis')).not.toBeInTheDocument()
    })
  })

  it('shows an error message when deleting a project fails', async () => {
    const projects = [{ id: 'p1', title: 'My Thesis', created_at: '2026-01-15T00:00:00Z' }]
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        return Promise.resolve(jsonResponse({ detail: 'server error' }, false, 500))
      }
      return Promise.resolve(jsonResponse(projects))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderLanding()
    await screen.findByText('My Thesis')

    fireEvent.click(screen.getByRole('button', { name: strings.projectLandingDeleteButton }))
    fireEvent.click(screen.getByRole('button', { name: strings.projectLandingDeleteConfirmButton }))

    expect(await screen.findByText(strings.projectLandingDeleteErrorMessage)).toBeInTheDocument()
    expect(screen.getByText('My Thesis')).toBeInTheDocument()
  })
})
