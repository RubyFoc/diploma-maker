import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useChapterLocks } from './useChapterLocks'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

const block = { id: 'b1', content: 'Some text.', content_hash: 'h1', order: 0 }

describe('useChapterLocks', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('returns no locked blocks without fetching when chapterId is null', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChapterLocks(null))

    expect(result.current).toMatchObject({ lockedBlockIds: new Set(), isLoading: false })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('fetches existing locks and reports locked block ids', async () => {
    const locks = [
      { id: 'l1', chapter_id: 'c1', block_id: 'b1', block_content_hash: 'h1', char_range: null, created_at: 'now' },
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(locks)))

    const { result } = renderHook(() => useChapterLocks('c1'))

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.lockedBlockIds).toEqual(new Set(['b1']))
  })

  it('toggleLock creates a lock for an unlocked block', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return Promise.resolve(
          jsonResponse(
            { id: 'l1', chapter_id: 'c1', block_id: 'b1', block_content_hash: 'h1', char_range: null, created_at: 'now' },
            true,
            201,
          ),
        )
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChapterLocks('c1'))
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    await act(async () => {
      await result.current.toggleLock(block)
    })

    expect(result.current.lockedBlockIds).toEqual(new Set(['b1']))
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/locks`,
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('toggleLock removes an existing lock for a locked block', async () => {
    const existingLock = {
      id: 'l1',
      chapter_id: 'c1',
      block_id: 'b1',
      block_content_hash: 'h1',
      char_range: null,
      created_at: 'now',
    }
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        return Promise.resolve({ ok: true, status: 204, json: () => Promise.reject(new Error('no body')), text: () => Promise.resolve('') } as unknown as Response)
      }
      return Promise.resolve(jsonResponse([existingLock]))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChapterLocks('c1'))
    await waitFor(() => expect(result.current.lockedBlockIds).toEqual(new Set(['b1'])))

    await act(async () => {
      await result.current.toggleLock(block)
    })

    expect(result.current.lockedBlockIds).toEqual(new Set())
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/locks/l1`,
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('toggleLock swallows a stale-hash failure without changing lock state', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ detail: 'stale lock' }, false, 409))
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChapterLocks('c1'))
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    await act(async () => {
      await result.current.toggleLock(block)
    })

    expect(result.current.lockedBlockIds).toEqual(new Set())
  })

  it('swallows a fetch failure when loading locks to an empty set', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'server error' }, false, 500)))

    const { result } = renderHook(() => useChapterLocks('c1'))

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.lockedBlockIds).toEqual(new Set())
  })
})
