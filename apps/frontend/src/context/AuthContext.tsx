import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'

export interface AuthState {
  accessToken: string | null
}

export const ACCESS_TOKEN_STORAGE_KEY = 'diploma-maker.accessToken'

export const emptyAuthState: AuthState = { accessToken: null }

function readStoredAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)
}

interface AuthContextValue {
  auth: AuthState
  setAuth: Dispatch<SetStateAction<AuthState>>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(() => ({ accessToken: readStoredAccessToken() }))

  useEffect(() => {
    if (auth.accessToken === null) {
      localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY)
      return
    }
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, auth.accessToken)
  }, [auth.accessToken])

  const value = useMemo(() => ({ auth, setAuth }), [auth])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
