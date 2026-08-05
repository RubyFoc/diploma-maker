import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { autoDetectInstitution, listInstitutions, uploadInstitutionSample } from './institutionService'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

describe('institutionService', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('listInstitutions fetches /formatting/institution-configs and returns the parsed list', async () => {
    const institutions = [{ institution_id: 'i1', institution_name: 'Test University' }]
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(institutions))
    vi.stubGlobal('fetch', fetchMock)

    const result = await listInstitutions()

    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/formatting/institution-configs`, expect.anything())
    expect(result).toEqual(institutions)
  })

  it('listInstitutions throws a clear error including status and body on a non-2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'server error' }, false, 500))
    vi.stubGlobal('fetch', fetchMock)

    await expect(listInstitutions()).rejects.toThrow(/500/)
  })

  it('uploadInstitutionSample posts multipart form data without a manual Content-Type header', async () => {
    const institution = { institution_id: 'i2', institution_name: 'New University' }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(institution, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    const file = new File(['sample content'], 'sample.docx')
    const result = await uploadInstitutionSample('New University', file)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE_URL}/formatting/institution-configs/upload`)
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect(init.body.get('institution_name')).toBe('New University')
    expect(init.body.get('file')).toBe(file)
    expect(init.headers).toBeUndefined()
    expect(result).toEqual(institution)
  })

  it('uploadInstitutionSample throws a clear error including status and body on a non-2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'bad file' }, false, 422))
    vi.stubGlobal('fetch', fetchMock)

    await expect(uploadInstitutionSample('New University', new File(['x'], 'x.docx'))).rejects.toThrow(/422/)
  })

  it('autoDetectInstitution posts the university name and returns the parsed institution on success', async () => {
    const institution = { institution_id: 'i3', institution_name: 'Auto University' }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(institution, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    const result = await autoDetectInstitution('Auto University')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE_URL}/formatting/institution-configs/auto-detect`)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ institution_name: 'Auto University' })
    expect(result).toEqual(institution)
  })

  it('autoDetectInstitution resolves to null (not a thrown error) when the backend returns 404', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ detail: "Could not automatically determine formatting requirements for 'Unknown University'." }, false, 404),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await autoDetectInstitution('Unknown University')

    expect(result).toBeNull()
  })

  it('autoDetectInstitution still throws on a non-404 non-2xx response (e.g. 502 search failure)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'search backend unavailable' }, false, 502))
    vi.stubGlobal('fetch', fetchMock)

    await expect(autoDetectInstitution('Some University')).rejects.toThrow(/502/)
  })
})
