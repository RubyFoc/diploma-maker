import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useDocument } from '../context/DocumentContext'
import { autoDetectInstitution, listInstitutions, uploadInstitutionSample } from '../services/institutionService'
import type { InstitutionSummary } from '../types/institution'
import { strings } from '../strings'
import './Onboarding.css'

interface NewProjectSetupProps {
  /** Called once the user submits, with whichever institution id (if any) was resolved. */
  onSubmit: (institutionId: string | null) => void
  onCancel: () => void
  isSubmitting: boolean
}

/**
 * University select/upload/auto-detect + required-sources UI shown when creating a new
 * project (TASK-INT-18). Previously part of the account-level `Onboarding` gate; moved here so
 * the institution choice (and required sources) are scoped per project instead of per account.
 *
 * Institution choice stays local to this component until "Create Project" is submitted — a
 * project may be created with no institution at all, which the old onboarding gate never
 * actually allowed (it blocked entry to the whole app until one was picked).
 *
 * Required sources still flow through `DocumentContext.pendingRequiredSources`, matching
 * `useNewProject`'s existing flush-on-create convention (TASK-E14-4).
 */
export function NewProjectSetup({ onSubmit, onCancel, isSubmitting }: NewProjectSetupProps) {
  const { document: doc, setDocument } = useDocument()

  const [institutions, setInstitutions] = useState<InstitutionSummary[]>([])
  const [institutionsError, setInstitutionsError] = useState<string | null>(null)
  const [selectedInstitutionId, setSelectedInstitutionId] = useState('')
  const [chosenInstitutionId, setChosenInstitutionId] = useState<string | null>(null)

  const [uploadName, setUploadName] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  const [autoDetectName, setAutoDetectName] = useState('')
  const [autoDetectMessage, setAutoDetectMessage] = useState<string | null>(null)
  const [isAutoDetecting, setIsAutoDetecting] = useState(false)

  const [requiredSourceAuthor, setRequiredSourceAuthor] = useState('')
  const [requiredSourceTitle, setRequiredSourceTitle] = useState('')

  useEffect(() => {
    listInstitutions()
      .then(setInstitutions)
      .catch(() => setInstitutionsError(strings.newProjectSetupInstitutionSelectError))
  }, [])

  const handleSelectInstitution = (institutionId: string) => {
    setSelectedInstitutionId(institutionId)
    setChosenInstitutionId(institutionId === '' ? null : institutionId)
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
      setChosenInstitutionId(institution.institution_id)
    } catch {
      setUploadError(strings.newProjectSetupInstitutionUploadError)
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
        setAutoDetectMessage(strings.newProjectSetupAutoDetectNotFoundMessage)
        return
      }
      setChosenInstitutionId(institution.institution_id)
    } catch {
      setAutoDetectMessage(strings.newProjectSetupAutoDetectError)
    } finally {
      setIsAutoDetecting(false)
    }
  }

  const handleAddRequiredSource = (event: FormEvent) => {
    event.preventDefault()
    const author = requiredSourceAuthor.trim()
    if (author === '') {
      return
    }
    const title = requiredSourceTitle.trim()
    setDocument((previous) => ({
      ...previous,
      pendingRequiredSources: [
        ...previous.pendingRequiredSources,
        title === '' ? { author } : { author, title },
      ],
    }))
    setRequiredSourceAuthor('')
    setRequiredSourceTitle('')
  }

  const handleRemoveRequiredSource = (index: number) => {
    setDocument((previous) => ({
      ...previous,
      pendingRequiredSources: previous.pendingRequiredSources.filter((_, i) => i !== index),
    }))
  }

  return (
    <div className="onboarding-shell">
      <section className="onboarding-card" aria-label={strings.newProjectSetupTitle}>
        <h1>{strings.newProjectSetupTitle}</h1>
        <p className="onboarding-subtitle">{strings.newProjectSetupSubtitle}</p>

        <h2 className="onboarding-section-title">{strings.newProjectSetupRequiredSourcesTitle}</h2>
        <p className="onboarding-subtitle">{strings.newProjectSetupRequiredSourcesSubtitle}</p>
        <form className="onboarding-form" onSubmit={handleAddRequiredSource}>
          <label>
            {strings.newProjectSetupRequiredSourceAuthorLabel}
            <input
              type="text"
              value={requiredSourceAuthor}
              onChange={(event) => setRequiredSourceAuthor(event.target.value)}
            />
          </label>
          <label>
            {strings.newProjectSetupRequiredSourceTitleLabel}
            <input
              type="text"
              value={requiredSourceTitle}
              onChange={(event) => setRequiredSourceTitle(event.target.value)}
            />
          </label>
          <button type="submit">{strings.newProjectSetupRequiredSourceAddButton}</button>
        </form>
        {doc.pendingRequiredSources.length > 0 && (
          <ul className="onboarding-required-sources-list">
            {doc.pendingRequiredSources.map((source, index) => (
              <li key={index}>
                <span>{source.title ? `${source.author} — ${source.title}` : source.author}</span>
                <button type="button" onClick={() => handleRemoveRequiredSource(index)}>
                  {strings.newProjectSetupRequiredSourceRemoveButton}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="onboarding-divider">{strings.newProjectSetupOrDivider}</div>

        <h2 className="onboarding-section-title">{strings.newProjectSetupAutoDetectTitle}</h2>
        <p className="onboarding-subtitle">{strings.newProjectSetupAutoDetectSubtitle}</p>
        <form className="onboarding-form" onSubmit={(event) => void handleAutoDetectSubmit(event)}>
          <label>
            {strings.newProjectSetupAutoDetectNameLabel}
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
              ? strings.newProjectSetupAutoDetectButtonPending
              : strings.newProjectSetupAutoDetectButton}
          </button>
        </form>

        <div className="onboarding-divider">{strings.newProjectSetupOrDivider}</div>

        <label>
          {strings.newProjectSetupInstitutionSelectLabel}
          <select
            value={selectedInstitutionId}
            onChange={(event) => handleSelectInstitution(event.target.value)}
          >
            <option value="">{strings.newProjectSetupInstitutionSelectPlaceholder}</option>
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

        <div className="onboarding-divider">{strings.newProjectSetupOrDivider}</div>

        <h2 className="onboarding-section-title">{strings.newProjectSetupInstitutionUploadTitle}</h2>
        <form className="onboarding-form" onSubmit={(event) => void handleUploadSubmit(event)}>
          <label>
            {strings.newProjectSetupInstitutionNameLabel}
            <input
              type="text"
              required
              value={uploadName}
              onChange={(event) => setUploadName(event.target.value)}
            />
          </label>
          <label>
            {strings.newProjectSetupInstitutionFileLabel}
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
            {strings.newProjectSetupInstitutionUploadButton}
          </button>
        </form>

        <div className="onboarding-actions">
          <button type="button" onClick={onCancel} disabled={isSubmitting}>
            {strings.newProjectSetupCancelButton}
          </button>
          <button type="button" onClick={() => onSubmit(chosenInstitutionId)} disabled={isSubmitting}>
            {strings.newProjectSetupCreateButton}
          </button>
        </div>
      </section>
    </div>
  )
}
