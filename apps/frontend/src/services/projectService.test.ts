import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACCESS_TOKEN_STORAGE_KEY } from '../context/AuthContext'
import {
  acceptDraft,
  createChapter,
  createProject,
  createSubchapter,
  deleteProject,
  generateChapterDraft,
  getProject,
  listProjects,
  listSubchapters,
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
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    localStorage.clear()
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
      parent_chapter_id: null,
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

  it('createSubchapter posts to /projects/{id}/chapters/{id}/subchapters with a title', async () => {
    const subchapter = {
      id: 'c2',
      project_id: 'p1',
      parent_chapter_id: 'c1',
      title: 'Section 1.1',
      order: 0,
      created_at: 'now',
      accepted_content: null,
      pending_draft: null,
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(subchapter, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    const result = await createSubchapter('p1', 'c1', 'Section 1.1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects/p1/chapters/c1/subchapters`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ title: 'Section 1.1' }) }),
    )
    expect(result).toEqual(subchapter)
  })

  it('listSubchapters fetches /projects/{id}/chapters/{id}/subchapters', async () => {
    const subchapters = [
      {
        id: 'c2',
        project_id: 'p1',
        parent_chapter_id: 'c1',
        title: 'Section 1.1',
        order: 0,
        created_at: 'now',
        accepted_content: null,
        pending_draft: null,
      },
    ]
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(subchapters))
    vi.stubGlobal('fetch', fetchMock)

    const result = await listSubchapters('p1', 'c1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects/p1/chapters/c1/subchapters`,
      expect.anything(),
    )
    expect(result).toEqual(subchapters)
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

  it('attaches an Authorization bearer header (using the stored access token) to project requests', async () => {
    const project = { id: 'p1', title: 'My Thesis', created_at: 'now', chapters: [] }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(project))
    vi.stubGlobal('fetch', fetchMock)

    await getProject('p1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects/p1`,
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('omits the Authorization header when there is no stored access token', async () => {
    localStorage.clear()
    const project = { id: 'p1', title: 'My Thesis', created_at: 'now', chapters: [] }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(project))
    vi.stubGlobal('fetch', fetchMock)

    await getProject('p1')

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers).not.toHaveProperty('Authorization')
  })

  it('listProjects fetches /projects and returns the parsed summary list', async () => {
    const projects = [
      { id: 'p1', title: 'My Thesis', created_at: 'now' },
      { id: 'p2', title: 'Other Thesis', created_at: 'earlier' },
    ]
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(projects))
    vi.stubGlobal('fetch', fetchMock)

    const result = await listProjects()

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects`,
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
    expect(result).toEqual(projects)
  })

  it('listProjects throws a clear error including status and body on a non-2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'server error' }, false, 500))
    vi.stubGlobal('fetch', fetchMock)

    await expect(listProjects()).rejects.toThrow(/500/)
  })

  it('deleteProject sends a DELETE to /projects/{id} with the auth header and resolves on 204', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: () => Promise.reject(new Error('204 responses have no body')),
      text: () => Promise.resolve(''),
    } as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)

    const result = await deleteProject('p1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects/p1`,
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
    expect(result).toBeUndefined()
  })

  it('deleteProject throws a clear error including status and body on a non-2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'not found' }, false, 404))
    vi.stubGlobal('fetch', fetchMock)

    await expect(deleteProject('missing')).rejects.toThrow(/404/)
  })
})
