import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '../context/AuthContext'
import { strings } from '../strings'
import { Onboarding } from './Onboarding'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

function AccessTokenProbe() {
  const { auth } = useAuth()
  return <p data-testid="access-token">{auth.accessToken ?? 'none'}</p>
}

function renderOnboarding() {
  render(
    <AuthProvider>
      <Onboarding />
      <AccessTokenProbe />
    </AuthProvider>,
  )
}

describe('Onboarding', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('registers and stores the returned access token on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ access_token: 'tok1', token_type: 'bearer' }, true, 201))
    vi.stubGlobal('fetch', fetchMock)

    renderOnboarding()

    fireEvent.change(screen.getByLabelText(strings.onboardingEmailLabel), {
      target: { value: 'user@example.com' },
    })
    fireEvent.change(screen.getByLabelText(strings.onboardingPasswordLabel), {
      target: { value: 'password123' },
    })
    fireEvent.click(screen.getByRole('button', { name: strings.onboardingRegisterButton }))

    expect(await screen.findByTestId('access-token')).toHaveTextContent('tok1')
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/auth/register`,
      expect.objectContaining({
        body: JSON.stringify({ email: 'user@example.com', password: 'password123' }),
      }),
    )
  })

  it('logs in and stores the returned access token on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ access_token: 'tok2', token_type: 'bearer' }, true, 200))
    vi.stubGlobal('fetch', fetchMock)

    renderOnboarding()

    fireEvent.change(screen.getByLabelText(strings.onboardingEmailLabel), {
      target: { value: 'user@example.com' },
    })
    fireEvent.change(screen.getByLabelText(strings.onboardingPasswordLabel), {
      target: { value: 'password123' },
    })
    fireEvent.click(screen.getByRole('button', { name: strings.onboardingLoginButton }))

    expect(await screen.findByTestId('access-token')).toHaveTextContent('tok2')
    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/auth/login`, expect.anything())
  })

  it('shows an error and does not store a token when registration fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'already registered' }, false, 409))
    vi.stubGlobal('fetch', fetchMock)

    renderOnboarding()

    fireEvent.change(screen.getByLabelText(strings.onboardingEmailLabel), {
      target: { value: 'user@example.com' },
    })
    fireEvent.change(screen.getByLabelText(strings.onboardingPasswordLabel), {
      target: { value: 'password123' },
    })
    fireEvent.click(screen.getByRole('button', { name: strings.onboardingRegisterButton }))

    expect(await screen.findByText(strings.onboardingAuthError)).toBeInTheDocument()
    expect(screen.getByTestId('access-token')).toHaveTextContent('none')
  })
})
