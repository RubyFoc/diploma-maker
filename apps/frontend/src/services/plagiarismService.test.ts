import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { checkPlagiarism, checkPlagiarismFile } from './plagiarismService'

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
      originality_score: 0.9,
      flagged: false,
      reasons: [],
      sentence_flags: [],
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
      originality_score: 0.5,
      flagged: true,
      reasons: ['matches known source'],
      sentence_flags: [],
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

  it('posts a file as multipart FormData to /plagiarism/check-file without a Content-Type header', async () => {
    const result = {
      plagiarism_score: 0.3,
      ai_fingerprint_score: 0.1,
      originality_score: 0.7,
      flagged: false,
      reasons: [],
      sentence_flags: [{ text: 'A sentence.', plagiarism_score: 0.1, is_plagiarized: false, is_ai_like: false }],
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(result))
    vi.stubGlobal('fetch', fetchMock)

    const file = new File(['content'], 'thesis.docx')
    const response = await checkPlagiarismFile(file)

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/plagiarism/check-file`,
      expect.objectContaining({ method: 'POST' }),
    )
    const callInit = fetchMock.mock.calls[0][1]
    expect(callInit.headers).toBeUndefined()
    expect(callInit.body).toBeInstanceOf(FormData)
    expect(response).toEqual(result)
  })

  it('throws a clear error including status and body when the file check fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse('unsupported file type', false, 400))
    vi.stubGlobal('fetch', fetchMock)

    const file = new File(['content'], 'notes.txt')

    await expect(checkPlagiarismFile(file)).rejects.toThrow(/400/)
  })
})
