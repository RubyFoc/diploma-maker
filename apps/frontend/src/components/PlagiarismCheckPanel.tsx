import { useState } from 'react'
import { strings } from '../strings'
import { checkPlagiarism } from '../services/plagiarismService'
import type { PlagiarismCheckResult } from '../types/project'
import './PlagiarismCheckPanel.css'

/**
 * Standalone panel for checking arbitrary pasted text for plagiarism/AI-fingerprint
 * risk, independent of any project or chapter. Manages its own local state (text,
 * result, loading, error) rather than reaching for a shared context, per ADR-0008 —
 * this feature has no state worth sharing beyond this component.
 */
export function PlagiarismCheckPanel() {
  const [text, setText] = useState('')
  const [result, setResult] = useState<PlagiarismCheckResult | null>(null)
  const [isChecking, setIsChecking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleCheck = async () => {
    if (text.trim() === '' || isChecking) {
      return
    }

    setIsChecking(true)
    setError(null)

    try {
      const checkResult = await checkPlagiarism(text)
      setResult(checkResult)
    } catch {
      setResult(null)
      setError(strings.plagiarismCheckErrorMessage)
    } finally {
      setIsChecking(false)
    }
  }

  return (
    <section className="plagiarism-check-panel" aria-label={strings.plagiarismCheckTitle}>
      <h2>{strings.plagiarismCheckTitle}</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void handleCheck()
        }}
      >
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={strings.plagiarismCheckTextareaPlaceholder}
          aria-label={strings.plagiarismCheckTextareaPlaceholder}
          disabled={isChecking}
        />
        <div>
          <button type="submit" disabled={text.trim() === '' || isChecking}>
            {isChecking ? strings.plagiarismCheckButtonPending : strings.plagiarismCheckButton}
          </button>
        </div>
      </form>

      {error && <p className="plagiarism-check-error">{error}</p>}

      {result && (
        <div className="plagiarism-check-result">
          <p
            className={`plagiarism-check-banner ${
              result.flagged ? 'plagiarism-check-banner--flagged' : 'plagiarism-check-banner--clear'
            }`}
          >
            {result.flagged ? strings.plagiarismCheckFlaggedMessage : strings.plagiarismCheckNotFlaggedMessage}
          </p>
          <div className="plagiarism-check-scores">
            <span>
              {strings.plagiarismCheckScoreLabel}: {Math.round(result.plagiarism_score * 100)}%
            </span>
            <span>
              {strings.plagiarismCheckAiFingerprintScoreLabel}: {Math.round(result.ai_fingerprint_score * 100)}%
            </span>
          </div>
          {result.flagged && result.reasons.length > 0 && (
            <div>
              <h3>{strings.plagiarismCheckReasonsTitle}</h3>
              <ul>
                {result.reasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
