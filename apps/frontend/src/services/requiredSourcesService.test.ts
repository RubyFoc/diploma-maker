import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACCESS_TOKEN_STORAGE_KEY } from '../context/AuthContext'
import { createRequiredSource, listRequiredSources } from './requiredSourcesService'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

describe('requiredSourcesService', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('createRequiredSource posts author/title and returns the created source', async () => {
    const source = {
      id: 'r1',
      project_id: 'p1',
      author: 'Jane Doe',
      title: 'A Study of Things',
      year: null,
      created_at: 'now',
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(source, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    const result = await createRequiredSource('p1', 'Jane Doe', 'A Study of Things')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects/p1/required-sources`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ author: 'Jane Doe', title: 'A Study of Things' }),
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
    expect(result).toEqual(source)
  })

  it('createRequiredSource omits title as null when not provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    await createRequiredSource('p1', 'Jane Doe')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/projects/p1/required-sources`,
      expect.objectContaining({ body: JSON.stringify({ author: 'Jane Doe', title: null }) }),
    )
  })

  it('listRequiredSources fetches /projects/{id}/required-sources', async () => {
    const sources = [
      { id: 'r1', project_id: 'p1', author: 'Jane Doe', title: null, year: null, created_at: 'now' },
    ]
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(sources))
    vi.stubGlobal('fetch', fetchMock)

    const result = await listRequiredSources('p1')

    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/projects/p1/required-sources`, expect.anything())
    expect(result).toEqual(sources)
  })

  it('throws a clear error including status and body on a non-2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'not found' }, false, 404))
    vi.stubGlobal('fetch', fetchMock)

    await expect(listRequiredSources('missing')).rejects.toThrow(/404/)
  })
})
