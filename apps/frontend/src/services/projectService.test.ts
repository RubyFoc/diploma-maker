import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  acceptDraft,
  createChapter,
  createProject,
  generateChapterDraft,
  getProject,
} from './projectService'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

describe('projectService', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('createProject posts to /projects with an optional title and returns the parsed project', async () => {
    const project = { id: 'p1', title: 'My Thesis', created_at: 'now', chapters: [] }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(project))
    vi.stubGlobal('fetch', fetchMock)

    const result = await createProject('My Thesis')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ title: 'My Thesis' }),
      }),
    )
    expect(result).toEqual(project)
  })

  it('createProject omits title from the body when not provided', async () => {
    const project = { id: 'p1', title: 'Untitled', created_at: 'now', chapters: [] }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(project))
    vi.stubGlobal('fetch', fetchMock)

    await createProject()

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects`,
      expect.objectContaining({ body: JSON.stringify({}) }),
    )
  })

  it('getProject fetches /projects/{id}', async () => {
    const project = { id: 'p1', title: 'My Thesis', created_at: 'now', chapters: [] }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(project))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getProject('p1')

    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/projects/p1`, expect.anything())
    expect(result).toEqual(project)
  })

  it('createChapter posts to /projects/{id}/chapters with a title', async () => {
    const chapter = {
      id: 'c1',
      project_id: 'p1',
      title: 'Chapter 1',
      order: 0,
      created_at: 'now',
      accepted_content: null,
      pending_draft: null,
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(chapter, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    const result = await createChapter('p1', 'Chapter 1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects/p1/chapters`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ title: 'Chapter 1' }) }),
    )
    expect(result).toEqual(chapter)
  })

  it('generateChapterDraft posts an instruction to the generate endpoint', async () => {
    const version = {
      id: 'v1',
      chapter_id: 'c1',
      version_number: 1,
      content: 'Generated text',
      created_at: 'now',
      status: 'draft' as const,
      parent_version_id: null,
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(version, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    const result = await generateChapterDraft('p1', 'c1', 'Write the intro')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects/p1/chapters/c1/generate`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ instruction: 'Write the intro' }),
      }),
    )
    expect(result).toEqual(version)
  })

  it('acceptDraft posts to /versions/{id}/accept', async () => {
    const version = {
      id: 'v1',
      chapter_id: 'c1',
      version_number: 1,
      content: 'Generated text',
      created_at: 'now',
      status: 'accepted' as const,
      parent_version_id: null,
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(version))
    vi.stubGlobal('fetch', fetchMock)

    const result = await acceptDraft('v1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/versions/v1/accept`,
      expect.objectContaining({ method: 'POST' }),
    )
    expect(result).toEqual(version)
  })

  it('throws a clear error including status and body on a non-2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'not found' }, false, 404))
    vi.stubGlobal('fetch', fetchMock)

    await expect(getProject('missing')).rejects.toThrow(/404/)
  })

  it('propagates a 502 generation failure as a thrown error', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'llm failed' }, false, 502))
    vi.stubGlobal('fetch', fetchMock)

    await expect(generateChapterDraft('p1', 'c1', 'do it')).rejects.toThrow(/502/)
  })
})
