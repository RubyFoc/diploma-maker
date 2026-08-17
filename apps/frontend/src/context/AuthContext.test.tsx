import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { AUTH_EXPIRED_EVENT } from '../services/authEvents'
import { ACCESS_TOKEN_STORAGE_KEY, AuthProvider, useAuth } from './AuthContext'

function Probe() {
  const { auth } = useAuth()
  return <span>{auth.accessToken ?? 'signed-out'}</span>
}

describe('AuthContext', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('clears the stored access token when AUTH_EXPIRED_EVENT fires', async () => {
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'stale-token')
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(await screen.findByText('stale-token')).toBeInTheDocument()

    act(() => {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
    })

    expect(await screen.findByText('signed-out')).toBeInTheDocument()
    expect(localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull()
  })
})
