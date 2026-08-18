import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { AUTH_EXPIRED_EVENT } from '../services/authEvents'

export interface AuthState {
  accessToken: string | null
}

export const ACCESS_TOKEN_STORAGE_KEY = 'diploma-maker.accessToken'

export const emptyAuthState: AuthState = { accessToken: null }

function readStoredAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)
}

function persistAccessToken(accessToken: string | null): void {
  if (accessToken === null) {
    localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY)
  } else {
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, accessToken)
  }
}

interface AuthContextValue {
  auth: AuthState
  setAuth: (next: AuthState) => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuthState] = useState<AuthState>(() => ({ accessToken: readStoredAccessToken() }))

  // Persists to localStorage synchronously, inline with the state update — NOT via a `useEffect`
  // keyed on `auth.accessToken` (the previous approach). React fires effects bottom-up (children
  // before parents) within one commit, so a child mounted as a direct result of this same auth
  // change (e.g. `ProjectLanding`'s own mount `useEffect` loading the project list right after
  // login) could run its fetch — which reads the token straight out of localStorage, see
  // `projectService.ts`'s `authHeaders` — before this provider's own effect had a chance to write
  // it there, sending that very first authenticated request out with no token at all. The
  // resulting 401 was then treated as a real "your session expired" signal (`authEvents`'s 401
  // listener), logging the user right back out to the login screen — user report: unable to get
  // past the login page at all, since every login attempt raced this exact spurious 401.
  const setAuth = useCallback((next: AuthState) => {
    persistAccessToken(next.accessToken)
    setAuthState(next)
  }, [])

  useEffect(() => {
    const handleAuthExpired = () => setAuth({ accessToken: null })
    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired)
  }, [setAuth])

  const value = useMemo(() => ({ auth, setAuth }), [auth, setAuth])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
