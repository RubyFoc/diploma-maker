import { act, fireEvent, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { AUTH_EXPIRED_EVENT } from '../services/authEvents'
import { ACCESS_TOKEN_STORAGE_KEY, AuthProvider, useAuth } from './AuthContext'

function Probe() {
  const { auth } = useAuth()
  return <span>{auth.accessToken ?? 'signed-out'}</span>
}

/** Mimics `ProjectLanding`'s own mount-time `useEffect` firing a fetch that reads the token
 * straight out of localStorage (`projectService.ts`'s `authHeaders`), rather than from React
 * state/props — the exact shape of the real race this component is meant to catch. */
function ChildThatReadsTokenOnMount({ onRead }: { onRead: (token: string | null) => void }) {
  useEffect(() => {
    onRead(localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return null
}

function LoginButton() {
  const { setAuth } = useAuth()
  return (
    <button type="button" onClick={() => setAuth({ accessToken: 'fresh-token' })}>
      Log in
    </button>
  )
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

  it('persists a new access token to localStorage before any child mount effect can run (user report: stuck on login)', () => {
    // A child that mounts only once `auth.accessToken` is set — same shape as `App`'s `Gate`
    // switching from `Onboarding` to the authenticated view once a token exists.
    function Gate() {
      const { auth } = useAuth()
      const [readToken, setReadToken] = useState<string | null>('not-read-yet')
      return (
        <>
          {auth.accessToken !== null && <ChildThatReadsTokenOnMount onRead={setReadToken} />}
          <span>{readToken ?? 'null'}</span>
        </>
      )
    }

    render(
      <AuthProvider>
        <LoginButton />
        <Gate />
      </AuthProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))

    // If localStorage were only written via a `useEffect` keyed on `auth.accessToken` (the
    // previous implementation), `ChildThatReadsTokenOnMount`'s own mount effect — a descendant,
    // so it fires first within the same commit — would read `null` here, reproducing the
    // spurious first-request-after-login 401 that logged users right back out.
    expect(screen.getByText('fresh-token')).toBeInTheDocument()
    expect(localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe('fresh-token')
  })
})
