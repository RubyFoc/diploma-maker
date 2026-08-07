import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { login, register } from '../services/authService'
import { strings } from '../strings'
import './Onboarding.css'

/**
 * Login/register gate (TASK-E10-1, simplified by TASK-INT-18). Collects an email/password and
 * stores the returned access token in `AuthContext`; once a token exists, `App`'s `Gate` stops
 * rendering this component in favor of `AuthenticatedApp`. University selection/upload and
 * required-sources setup used to live here as a second step but are now part of the
 * "create new project" flow (`NewProjectSetup`, via `ProjectLanding`), scoped per project.
 */
export function Onboarding() {
  const { setAuth } = useAuth()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [authError, setAuthError] = useState<string | null>(null)
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false)

  const handleAuthSubmit = async (submit: (email: string, password: string) => Promise<{ access_token: string }>) => {
    setIsSubmittingAuth(true)
    setAuthError(null)
    try {
      const result = await submit(email, password)
      setAuth({ accessToken: result.access_token })
    } catch {
      setAuthError(strings.onboardingAuthError)
    } finally {
      setIsSubmittingAuth(false)
    }
  }

  return (
    <div className="onboarding-shell">
      <section className="onboarding-card" aria-label={strings.onboardingTitle}>
        <h1>{strings.onboardingTitle}</h1>
        <p className="onboarding-subtitle">{strings.onboardingSubtitle}</p>
        {authError !== null && <p className="onboarding-error" role="alert">{authError}</p>}
        <form className="onboarding-form">
          <label>
            {strings.onboardingEmailLabel}
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            {strings.onboardingPasswordLabel}
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <div className="onboarding-actions">
            <button
              type="button"
              disabled={isSubmittingAuth}
              onClick={() => void handleAuthSubmit(register)}
            >
              {strings.onboardingRegisterButton}
            </button>
            <button
              type="button"
              disabled={isSubmittingAuth}
              onClick={() => void handleAuthSubmit(login)}
            >
              {strings.onboardingLoginButton}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
