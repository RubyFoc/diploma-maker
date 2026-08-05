import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useAuth } from '../context/AuthContext'
import { useDocument } from '../context/DocumentContext'
import { login, register } from '../services/authService'
import { autoDetectInstitution, listInstitutions, uploadInstitutionSample } from '../services/institutionService'
import type { InstitutionSummary } from '../types/institution'
import { strings } from '../strings'
import './Onboarding.css'

/**
 * Registration/login + university selection/upload onboarding gate (TASK-E10-1).
 *
 * Step 1 collects an email/password and stores the returned access token in
 * `AuthContext`. Step 2 (shown once a token exists) lets the user pick an
 * existing institution config or upload a new sample; either path stores the
 * resulting `institution_id` in `DocumentContext`. Once both steps are done,
 * `App` stops rendering this component in favor of `Workspace`.
 */
export function Onboarding() {
  const { auth, setAuth } = useAuth()
  const { document: doc, setDocument } = useDocument()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [authError, setAuthError] = useState<string | null>(null)
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false)

  const [institutions, setInstitutions] = useState<InstitutionSummary[]>([])
  const [institutionsError, setInstitutionsError] = useState<string | null>(null)
  const [selectedInstitutionId, setSelectedInstitutionId] = useState('')

  const [uploadName, setUploadName] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  const [autoDetectName, setAutoDetectName] = useState('')
  const [autoDetectMessage, setAutoDetectMessage] = useState<string | null>(null)
  const [isAutoDetecting, setIsAutoDetecting] = useState(false)

  const hasToken = auth.accessToken !== null

  useEffect(() => {
    if (!hasToken) {
      return
    }
    listInstitutions()
      .then(setInstitutions)
      .catch(() => setInstitutionsError(strings.onboardingInstitutionSelectError))
  }, [hasToken])

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

  const handleSelectInstitution = (institutionId: string) => {
    setSelectedInstitutionId(institutionId)
    if (institutionId === '') {
      return
    }
    setDocument((previous) => ({ ...previous, institutionId }))
  }

  const handleUploadSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (uploadFile === null) {
      return
    }
    setIsUploading(true)
    setUploadError(null)
    try {
      const institution = await uploadInstitutionSample(uploadName, uploadFile)
      setDocument((previous) => ({ ...previous, institutionId: institution.institution_id }))
    } catch {
      setUploadError(strings.onboardingInstitutionUploadError)
    } finally {
      setIsUploading(false)
    }
  }

  const handleAutoDetectSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setIsAutoDetecting(true)
    setAutoDetectMessage(null)
    try {
      const institution = await autoDetectInstitution(autoDetectName)
      if (institution === null) {
        setAutoDetectMessage(strings.onboardingInstitutionAutoDetectNotFoundMessage)
        return
      }
      setDocument((previous) => ({ ...previous, institutionId: institution.institution_id }))
    } catch {
      setAutoDetectMessage(strings.onboardingInstitutionAutoDetectError)
    } finally {
      setIsAutoDetecting(false)
    }
  }

  if (!hasToken) {
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

  return (
    <div className="onboarding-shell">
      <section className="onboarding-card" aria-label={strings.onboardingInstitutionStepTitle}>
        <h1>{strings.onboardingInstitutionStepTitle}</h1>
        <p className="onboarding-subtitle">{strings.onboardingInstitutionStepSubtitle}</p>
        {doc.institutionId !== null ? null : (
          <>
            <h2 className="onboarding-section-title">{strings.onboardingInstitutionAutoDetectTitle}</h2>
            <p className="onboarding-subtitle">{strings.onboardingInstitutionAutoDetectSubtitle}</p>
            <form className="onboarding-form" onSubmit={(event) => void handleAutoDetectSubmit(event)}>
              <label>
                {strings.onboardingInstitutionAutoDetectNameLabel}
                <input
                  type="text"
                  required
                  value={autoDetectName}
                  onChange={(event) => setAutoDetectName(event.target.value)}
                />
              </label>
              {autoDetectMessage !== null && (
                <p className="onboarding-error" role="alert">
                  {autoDetectMessage}
                </p>
              )}
              <button type="submit" disabled={isAutoDetecting}>
                {isAutoDetecting
                  ? strings.onboardingInstitutionAutoDetectButtonPending
                  : strings.onboardingInstitutionAutoDetectButton}
              </button>
            </form>

            <div className="onboarding-divider">{strings.onboardingOrDivider}</div>

            <label>
              {strings.onboardingInstitutionSelectLabel}
              <select
                value={selectedInstitutionId}
                onChange={(event) => handleSelectInstitution(event.target.value)}
              >
                <option value="">{strings.onboardingInstitutionSelectPlaceholder}</option>
                {institutions.map((institution) => (
                  <option key={institution.institution_id} value={institution.institution_id}>
                    {institution.institution_name}
                  </option>
                ))}
              </select>
            </label>
            {institutionsError !== null && (
              <p className="onboarding-error" role="alert">
                {institutionsError}
              </p>
            )}

            <div className="onboarding-divider">{strings.onboardingOrDivider}</div>

            <h2 className="onboarding-section-title">{strings.onboardingInstitutionUploadTitle}</h2>
            <form className="onboarding-form" onSubmit={(event) => void handleUploadSubmit(event)}>
              <label>
                {strings.onboardingInstitutionNameLabel}
                <input
                  type="text"
                  required
                  value={uploadName}
                  onChange={(event) => setUploadName(event.target.value)}
                />
              </label>
              <label>
                {strings.onboardingInstitutionFileLabel}
                <input
                  type="file"
                  required
                  onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
                />
              </label>
              {uploadError !== null && (
                <p className="onboarding-error" role="alert">
                  {uploadError}
                </p>
              )}
              <button type="submit" disabled={isUploading}>
                {strings.onboardingInstitutionUploadButton}
              </button>
            </form>
          </>
        )}
      </section>
    </div>
  )
}
