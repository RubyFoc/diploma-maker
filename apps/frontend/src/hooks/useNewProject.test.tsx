import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useNewProject } from './useNewProject'
import { ChatProvider } from '../context/ChatContext'
import { DocumentProvider, useDocument } from '../context/DocumentContext'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <DocumentProvider>
      <ChatProvider>{children}</ChatProvider>
    </DocumentProvider>
  )
}

function useTestHooks() {
  return { newProject: useNewProject(), doc: useDocument() }
}

describe('useNewProject', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('creates a project without submitting any required sources when none are queued', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }, true, 201),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(useTestHooks, { wrapper })

    await act(async () => {
      await result.current.newProject()
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(result.current.doc.document.projectId).toBe('p1')
  })

  it('submits each queued required source against the newly created project, then clears the queue', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (String(url).endsWith('/projects') && init?.method === 'POST') {
        return Promise.resolve(
          jsonResponse({ id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }, true, 201),
        )
      }
      if (String(url).endsWith('/required-sources')) {
        return Promise.resolve(jsonResponse({ id: 'r1' }, true, 201))
      }
      return Promise.resolve(jsonResponse({ detail: 'unexpected request' }, false, 500))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(useTestHooks, { wrapper })
    act(() => {
      result.current.doc.setDocument((previous) => ({
        ...previous,
        pendingRequiredSources: [{ author: 'Jane Doe', title: 'A Study of Things' }],
      }))
    })

    await act(async () => {
      await result.current.newProject()
    })

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects/p1/required-sources`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ author: 'Jane Doe', title: 'A Study of Things' }),
      }),
    )
    expect(result.current.doc.document.pendingRequiredSources).toEqual([])
  })

  it('passes a chosen institution id through to project creation and reflects it on the created project', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (String(url).endsWith('/projects') && init?.method === 'POST') {
        expect(init.body).toBe(JSON.stringify({ institution_id: 'inst-1' }))
        return Promise.resolve(
          jsonResponse(
            { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [], institution_id: 'inst-1' },
            true,
            201,
          ),
        )
      }
      return Promise.resolve(jsonResponse({ detail: 'unexpected request' }, false, 500))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(useTestHooks, { wrapper })

    await act(async () => {
      await result.current.newProject('inst-1')
    })

    expect(result.current.doc.document.institutionId).toBe('inst-1')
  })

  it('still creates the project if a queued required source submission fails', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (String(url).endsWith('/projects') && init?.method === 'POST') {
        return Promise.resolve(
          jsonResponse({ id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }, true, 201),
        )
      }
      if (String(url).endsWith('/required-sources')) {
        return Promise.resolve(jsonResponse({ detail: 'server error' }, false, 500))
      }
      return Promise.resolve(jsonResponse({ detail: 'unexpected request' }, false, 500))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(useTestHooks, { wrapper })
    act(() => {
      result.current.doc.setDocument((previous) => ({
        ...previous,
        pendingRequiredSources: [{ author: 'Jane Doe' }],
      }))
    })

    await act(async () => {
      await result.current.newProject()
    })

    expect(result.current.doc.document.projectId).toBe('p1')
  })
})
