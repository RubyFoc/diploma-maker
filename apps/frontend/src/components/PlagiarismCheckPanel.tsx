import { useState } from 'react'
import { strings } from '../strings'
import { checkPlagiarism, checkPlagiarismFile } from '../services/plagiarismService'
import type { PlagiarismCheckResult } from '../types/project'
import { PlagiarismResultView } from './PlagiarismResultView'
import './PlagiarismCheckPanel.css'

type CheckMode = 'text' | 'file'

/**
 * Standalone panel for checking either pasted text or an uploaded .pdf/.docx file for
 * plagiarism/AI-fingerprint risk, independent of any project or chapter. Both modes share one
 * tab and one result view (per user request — file upload was originally its own tab, merged
 * into this panel instead) via a mode toggle; only the input control and the endpoint called
 * differ. Manages its own local state rather than reaching for a shared context, per ADR-0008 —
 * this feature has no state worth sharing beyond this component.
 */
export function PlagiarismCheckPanel() {
  const [mode, setMode] = useState<CheckMode>('text')
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<PlagiarismCheckResult | null>(null)
  const [isChecking, setIsChecking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSubmit = mode === 'text' ? text.trim() !== '' : file !== null

  const switchMode = (nextMode: CheckMode) => {
    setMode(nextMode)
    setResult(null)
    setError(null)
  }

  const handleCheck = async () => {
    if (!canSubmit || isChecking) {
      return
    }

    setIsChecking(true)
    setError(null)

    try {
      const checkResult =
        mode === 'text' ? await checkPlagiarism(text) : await checkPlagiarismFile(file as File)
      setResult(checkResult)
    } catch {
      setResult(null)
      setError(mode === 'text' ? strings.plagiarismCheckErrorMessage : strings.plagiarismUploadErrorMessage)
    } finally {
      setIsChecking(false)
    }
  }

  return (
    <section className="panel plagiarism-check-panel" aria-label={strings.plagiarismCheckTitle}>
      <h2>{strings.plagiarismCheckTitle}</h2>
      <div className="plagiarism-check-mode-toggle" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'text'}
          className={mode === 'text' ? 'plagiarism-check-mode plagiarism-check-mode--active' : 'plagiarism-check-mode'}
          onClick={() => switchMode('text')}
          disabled={isChecking}
        >
          {strings.plagiarismCheckModeTextLabel}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'file'}
          className={mode === 'file' ? 'plagiarism-check-mode plagiarism-check-mode--active' : 'plagiarism-check-mode'}
          onClick={() => switchMode('file')}
          disabled={isChecking}
        >
          {strings.plagiarismCheckModeFileLabel}
        </button>
      </div>
      <form
        className="plagiarism-check-form"
        onSubmit={(event) => {
          event.preventDefault()
          void handleCheck()
        }}
      >
        {mode === 'text' ? (
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={strings.plagiarismCheckTextareaPlaceholder}
            aria-label={strings.plagiarismCheckTextareaPlaceholder}
            disabled={isChecking}
          />
        ) : (
          <>
            <label htmlFor="plagiarism-check-file">{strings.plagiarismUploadFileLabel}</label>
            <input
              id="plagiarism-check-file"
              type="file"
              accept=".pdf,.docx"
              aria-label={strings.plagiarismUploadFileLabel}
              disabled={isChecking}
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </>
        )}
        <div className="plagiarism-check-form-actions">
          <button type="submit" disabled={!canSubmit || isChecking}>
            {isChecking
              ? strings.plagiarismCheckButtonPending
              : mode === 'text'
                ? strings.plagiarismCheckButton
                : strings.plagiarismUploadButton}
          </button>
        </div>
      </form>

      {error && <p className="plagiarism-check-error">{error}</p>}

      {result && <PlagiarismResultView result={result} />}
    </section>
  )
}
