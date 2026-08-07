import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACCESS_TOKEN_STORAGE_KEY } from '../context/AuthContext'
import { RequestError, listOperations, redoChapter, undoChapter } from './historyService'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

describe('historyService', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('listOperations fetches /chapters/{id}/operations with the auth header', async () => {
    const body = { operations: [{ id: 'o1', block_id: 'b1', created_at: 'now' }], applied_count: 1, total_operations: 1 }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body))
    vi.stubGlobal('fetch', fetchMock)

    const result = await listOperations('c1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/operations`,
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer test-token' }) }),
    )
    expect(result).toEqual(body)
  })

  it('undoChapter posts count and returns the updated version/cursor', async () => {
    const body = { version: { id: 'v1', chapter_id: 'c1', version_number: 2, content: 'x', manifest: null, created_at: 'now', status: 'draft', parent_version_id: null }, applied_count: 1, total_operations: 2 }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body))
    vi.stubGlobal('fetch', fetchMock)

    const result = await undoChapter('c1', 2)

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/undo`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ count: 2 }) }),
    )
    expect(result).toEqual(body)
  })

  it('undoChapter defaults count to 1', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ version: {}, applied_count: 0, total_operations: 1 }))
    vi.stubGlobal('fetch', fetchMock)

    await undoChapter('c1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/undo`,
      expect.objectContaining({ body: JSON.stringify({ count: 1 }) }),
    )
  })

  it('redoChapter posts count and returns the updated version/cursor', async () => {
    const body = { version: { id: 'v1', chapter_id: 'c1', version_number: 2, content: 'y', manifest: null, created_at: 'now', status: 'draft', parent_version_id: null }, applied_count: 2, total_operations: 2 }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body))
    vi.stubGlobal('fetch', fetchMock)

    const result = await redoChapter('c1', 1)

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/redo`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ count: 1 }) }),
    )
    expect(result).toEqual(body)
  })

  it('throws a RequestError exposing the status on a 409 conflict', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'nothing to undo' }, false, 409))
    vi.stubGlobal('fetch', fetchMock)

    await expect(undoChapter('c1')).rejects.toThrow(/409/)

    try {
      await undoChapter('c1')
      throw new Error('expected undoChapter to reject')
    } catch (error) {
      expect(error).toBeInstanceOf(RequestError)
      expect((error as RequestError).status).toBe(409)
    }
  })
})
