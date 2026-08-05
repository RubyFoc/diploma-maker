import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { login, register } from './authService'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

describe('authService', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('register posts email/password to /auth/register and returns the token', async () => {
    const token = { access_token: 'abc123', token_type: 'bearer' }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(token, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    const result = await register('user@example.com', 'password123')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/auth/register`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ email: 'user@example.com', password: 'password123' }),
      }),
    )
    expect(result).toEqual(token)
  })

  it('register throws a clear error including status and body on a 409 conflict', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'already registered' }, false, 409))
    vi.stubGlobal('fetch', fetchMock)

    await expect(register('user@example.com', 'password123')).rejects.toThrow(/409/)
  })

  it('login posts email/password to /auth/login and returns the token', async () => {
    const token = { access_token: 'xyz789', token_type: 'bearer' }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(token, true, 200))
    vi.stubGlobal('fetch', fetchMock)

    const result = await login('user@example.com', 'password123')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/auth/login`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ email: 'user@example.com', password: 'password123' }),
      }),
    )
    expect(result).toEqual(token)
  })

  it('login throws a clear error including status and body on a 401', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'bad credentials' }, false, 401))
    vi.stubGlobal('fetch', fetchMock)

    await expect(login('user@example.com', 'wrong')).rejects.toThrow(/401/)
  })
})
