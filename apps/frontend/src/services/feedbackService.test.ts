import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { recordSignal } from './feedbackService'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

describe('feedbackService', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('recordSignal posts to /feedback/signals with the signal payload and returns the parsed signal', async () => {
    const signal = {
      id: 's1',
      institution_id: 'inst-1',
      chapter_id: 'c1',
      version_id: 'v1',
      signal_type: 'approve' as const,
      created_at: 'now',
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(signal, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    const result = await recordSignal('inst-1', 'c1', 'v1', 'approve')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/feedback/signals`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          institution_id: 'inst-1',
          chapter_id: 'c1',
          version_id: 'v1',
          signal_type: 'approve',
        }),
      }),
    )
    expect(result).toEqual(signal)
  })

  it('throws a clear error including status and body on a non-2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'server error' }, false, 500))
    vi.stubGlobal('fetch', fetchMock)

    await expect(recordSignal('inst-1', 'c1', 'v1', 'reject')).rejects.toThrow(/500/)
  })
})
