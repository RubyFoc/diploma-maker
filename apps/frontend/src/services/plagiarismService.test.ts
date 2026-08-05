import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { checkPlagiarism } from './plagiarismService'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

describe('plagiarismService', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('posts text to /plagiarism/check and returns the parsed result', async () => {
    const result = {
      plagiarism_score: 0.1,
      ai_fingerprint_score: 0.2,
      flagged: false,
      reasons: [],
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(result))
    vi.stubGlobal('fetch', fetchMock)

    const response = await checkPlagiarism('some text')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/plagiarism/check`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ text: 'some text' }),
      }),
    )
    expect(response).toEqual(result)
  })

  it('includes source_excerpts in the body when provided', async () => {
    const result = {
      plagiarism_score: 0.5,
      ai_fingerprint_score: 0.6,
      flagged: true,
      reasons: ['matches known source'],
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(result))
    vi.stubGlobal('fetch', fetchMock)

    await checkPlagiarism('some text', ['excerpt one'])

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/plagiarism/check`,
      expect.objectContaining({
        body: JSON.stringify({ text: 'some text', source_excerpts: ['excerpt one'] }),
      }),
    )
  })

  it('throws a clear error including status and body on a non-2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'text is required' }, false, 422))
    vi.stubGlobal('fetch', fetchMock)

    await expect(checkPlagiarism('')).rejects.toThrow(/422/)
  })
})
