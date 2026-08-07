import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useChapterHistory } from './useChapterHistory'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

const version = {
  id: 'v1',
  chapter_id: 'c1',
  version_number: 2,
  content: 'reverted content',
  manifest: null,
  created_at: 'now',
  status: 'draft' as const,
  parent_version_id: null,
}

describe('useChapterHistory', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('does not fetch and reports no history when chapterId is null', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChapterHistory(null, vi.fn()))

    expect(result.current).toMatchObject({ history: null, isLoading: false, error: null })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('fetches the operations list on mount', async () => {
    const body = { operations: [{ id: 'o1', block_id: 'b1', created_at: 'now' }], applied_count: 1, total_operations: 1 }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(body)))

    const { result } = renderHook(() => useChapterHistory('c1', vi.fn()))

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.history).toEqual(body)
  })

  it('undo calls the backend with the given count, updates the cursor, and reports the new version', async () => {
    const onVersionUpdated = vi.fn()
    const fetchMock = vi.fn((url: string) => {
      if (String(url).endsWith('/operations')) {
        return Promise.resolve(
          jsonResponse({ operations: [{ id: 'o1', block_id: 'b1', created_at: 'now' }], applied_count: 1, total_operations: 1 }),
        )
      }
      if (String(url).endsWith('/undo')) {
        return Promise.resolve(jsonResponse({ version, applied_count: 0, total_operations: 1 }))
      }
      return Promise.resolve(jsonResponse({ detail: 'unexpected' }, false, 500))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChapterHistory('c1', onVersionUpdated))
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    await act(async () => {
      await result.current.undo(1)
    })

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/chapters/c1/undo`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ count: 1 }) }),
    )
    expect(onVersionUpdated).toHaveBeenCalledWith(version)
    expect(result.current.history?.applied_count).toBe(0)
    expect(result.current.error).toBeNull()
  })

  it('sets a distinct conflict error on a 409, without updating the draft', async () => {
    const onVersionUpdated = vi.fn()
    const fetchMock = vi.fn((url: string) => {
      if (String(url).endsWith('/operations')) {
        return Promise.resolve(jsonResponse({ operations: [], applied_count: 0, total_operations: 0 }))
      }
      return Promise.resolve(jsonResponse({ detail: 'nothing to undo' }, false, 409))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChapterHistory('c1', onVersionUpdated))
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    await act(async () => {
      await result.current.undo(1)
    })

    expect(result.current.error).toBe('conflict')
    expect(onVersionUpdated).not.toHaveBeenCalled()
  })

  it('refetches operations when draftKey changes even though chapterId stays the same', async () => {
    const firstBody = { operations: [{ id: 'o1', block_id: 'b1', created_at: 'now' }], applied_count: 1, total_operations: 1 }
    const secondBody = {
      operations: [
        { id: 'o1', block_id: 'b1', created_at: 'now' },
        { id: 'o2', block_id: 'b2', created_at: 'now' },
      ],
      applied_count: 2,
      total_operations: 2,
    }
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(firstBody)).mockResolvedValueOnce(jsonResponse(secondBody))
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(
      ({ draftKey }: { draftKey: string }) => useChapterHistory('c1', vi.fn(), draftKey),
      { initialProps: { draftKey: 'draft-1' } },
    )

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.history).toEqual(firstBody)

    rerender({ draftKey: 'draft-2' })

    await waitFor(() => expect(result.current.history).toEqual(secondBody))
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('sets a generic error on a non-409 failure', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (String(url).endsWith('/operations')) {
        return Promise.resolve(jsonResponse({ operations: [], applied_count: 0, total_operations: 0 }))
      }
      return Promise.resolve(jsonResponse({ detail: 'server error' }, false, 500))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChapterHistory('c1', vi.fn()))
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    await act(async () => {
      await result.current.redo(1)
    })

    expect(result.current.error).toBe('generic')
  })
})
