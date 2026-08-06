import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACCESS_TOKEN_STORAGE_KEY } from '../context/AuthContext'
import { createLock, deleteLock, listLocks } from './lockService'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

describe('lockService', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('listLocks fetches /chapters/{id}/locks with the auth header', async () => {
    const locks = [
      { id: 'l1', chapter_id: 'c1', block_id: 'b1', block_content_hash: 'h1', char_range: null, created_at: 'now' },
    ]
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(locks))
    vi.stubGlobal('fetch', fetchMock)

    const result = await listLocks('c1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/locks`,
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer test-token' }) }),
    )
    expect(result).toEqual(locks)
  })

  it('createLock posts block_id/block_content_hash and returns the created lock', async () => {
    const lock = { id: 'l1', chapter_id: 'c1', block_id: 'b1', block_content_hash: 'h1', char_range: null, created_at: 'now' }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(lock, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    const result = await createLock('c1', 'b1', 'h1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/locks`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ block_id: 'b1', block_content_hash: 'h1', char_range: null }),
      }),
    )
    expect(result).toEqual(lock)
  })

  it('createLock includes an optional char_range', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    await createLock('c1', 'b1', 'h1', { start: 0, end: 5 })

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/locks`,
      expect.objectContaining({
        body: JSON.stringify({ block_id: 'b1', block_content_hash: 'h1', char_range: { start: 0, end: 5 } }),
      }),
    )
  })

  it('createLock throws a clear error on a stale-hash 409', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'stale lock' }, false, 409))
    vi.stubGlobal('fetch', fetchMock)

    await expect(createLock('c1', 'b1', 'stale-hash')).rejects.toThrow(/409/)
  })

  it('deleteLock sends a DELETE and resolves on 204', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: () => Promise.reject(new Error('no body')),
      text: () => Promise.resolve(''),
    } as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)

    const result = await deleteLock('c1', 'l1')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/locks/l1`,
      expect.objectContaining({ method: 'DELETE' }),
    )
    expect(result).toBeUndefined()
  })
})
