import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useInstitutionConfig } from './useInstitutionConfig'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

describe('useInstitutionConfig', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('returns a null config without fetching when institutionId is null', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useInstitutionConfig(null))

    expect(result.current).toEqual({ config: null, isLoading: false })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('fetches and returns the config for a given institutionId', async () => {
    const config = { institution_id: 'i1', institution_name: 'Test University' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(config)))

    const { result } = renderHook(() => useInstitutionConfig('i1'))

    expect(result.current.isLoading).toBe(true)
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.config).toEqual(config)
  })

  it('swallows a fetch failure (e.g. 404) to a null config instead of throwing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'not found' }, false, 404)))

    const { result } = renderHook(() => useInstitutionConfig('unknown'))

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.config).toBeNull()
  })
})
