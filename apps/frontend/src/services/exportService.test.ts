import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exportProject } from './exportService'

const BASE_URL = 'http://localhost:8010'

function blobResponse(contentDisposition: string | null, ok = true, status = 200) {
  return {
    ok,
    status,
    headers: { get: (name: string) => (name === 'Content-Disposition' ? contentDisposition : null) },
    blob: () => Promise.resolve(new Blob(['fake docx bytes'])),
    text: () => Promise.resolve('error body'),
  } as unknown as Response
}

describe('exportService', () => {
  let clickSpy: ReturnType<typeof vi.spyOn>
  let createObjectURLMock: ReturnType<typeof vi.fn>
  let revokeObjectURLMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    createObjectURLMock = vi.fn().mockReturnValue('blob:fake-url')
    revokeObjectURLMock = vi.fn()
    vi.stubGlobal('URL', { createObjectURL: createObjectURLMock, revokeObjectURL: revokeObjectURLMock })
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    clickSpy.mockRestore()
  })

  it('fetches the export endpoint without institution_id when institutionId is null', async () => {
    const fetchMock = vi.fn().mockResolvedValue(blobResponse('attachment; filename="My Thesis.docx"'))
    vi.stubGlobal('fetch', fetchMock)

    await exportProject('p1', null)

    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/projects/p1/export`)
  })

  it('includes institution_id in the query string when provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue(blobResponse('attachment; filename="My Thesis.docx"'))
    vi.stubGlobal('fetch', fetchMock)

    await exportProject('p1', 'inst-1')

    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/projects/p1/export?institution_id=inst-1`)
  })

  it('triggers a download using the filename parsed from Content-Disposition', async () => {
    const fetchMock = vi.fn().mockResolvedValue(blobResponse('attachment; filename="My Thesis.docx"'))
    vi.stubGlobal('fetch', fetchMock)

    await exportProject('p1', null)

    expect(createObjectURLMock).toHaveBeenCalled()
    expect(clickSpy).toHaveBeenCalled()
    expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:fake-url')
  })

  it('falls back to a generic filename when Content-Disposition is missing', async () => {
    const fetchMock = vi.fn().mockResolvedValue(blobResponse(null))
    vi.stubGlobal('fetch', fetchMock)

    await expect(exportProject('p1', null)).resolves.toBeUndefined()
    expect(clickSpy).toHaveBeenCalled()
  })

  it('throws a clear error on a non-2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(blobResponse(null, false, 404))
    vi.stubGlobal('fetch', fetchMock)

    await expect(exportProject('missing', null)).rejects.toThrow(/404/)
  })
})
