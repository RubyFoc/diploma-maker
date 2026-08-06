import { strings } from '../strings'
import type { PlagiarismCheckResult } from '../types/project'
import './PlagiarismCheckPanel.css'

/**
 * Shared result view for both the paste-text and file-upload plagiarism check
 * panels, since the backend returns the exact same response shape for both.
 */
export function PlagiarismResultView({ result }: { result: PlagiarismCheckResult }) {
  return (
    <div className="plagiarism-check-result">
      <p
        className={`plagiarism-check-banner ${
          result.flagged ? 'plagiarism-check-banner--flagged' : 'plagiarism-check-banner--clear'
        }`}
      >
        {result.flagged ? strings.plagiarismCheckFlaggedMessage : strings.plagiarismCheckNotFlaggedMessage}
      </p>
      <div className="plagiarism-check-scores">
        <div className="plagiarism-check-score">
          <span className="plagiarism-check-score-label">
            <span>{strings.plagiarismCheckScoreLabel}</span>
            <span>{Math.round(result.plagiarism_score * 100)}%</span>
          </span>
          <div className="plagiarism-check-score-track">
            <div
              className="plagiarism-check-score-fill"
              style={{ width: `${Math.round(result.plagiarism_score * 100)}%` }}
            />
          </div>
        </div>
        <div className="plagiarism-check-score">
          <span className="plagiarism-check-score-label">
            <span>{strings.plagiarismCheckAiFingerprintScoreLabel}</span>
            <span>{Math.round(result.ai_fingerprint_score * 100)}%</span>
          </span>
          <div className="plagiarism-check-score-track">
            <div
              className="plagiarism-check-score-fill"
              style={{ width: `${Math.round(result.ai_fingerprint_score * 100)}%` }}
            />
          </div>
        </div>
        <div className="plagiarism-check-score">
          <span className="plagiarism-check-score-label">
            <span>{strings.plagiarismCheckOriginalityScoreLabel}</span>
            <span>{Math.round(result.originality_score * 100)}%</span>
          </span>
          <div className="plagiarism-check-score-track">
            <div
              className="plagiarism-check-score-fill"
              style={{ width: `${Math.round(result.originality_score * 100)}%` }}
            />
          </div>
        </div>
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
      {result.sentence_flags.length > 0 && (
        <div className="plagiarism-check-sentence-flags">
          <h3>{strings.plagiarismCheckSentenceFlagsTitle}</h3>
          <p>
            {result.sentence_flags.map((flag, index) => {
              const modifiers = [
                flag.is_plagiarized && 'plagiarism-check-sentence--plagiarized',
                flag.is_ai_like && 'plagiarism-check-sentence--ai-like',
              ]
                .filter(Boolean)
                .join(' ')
              return (
                <span key={index} className={`plagiarism-check-sentence ${modifiers}`.trim()}>
                  {flag.text}
                  {index < result.sentence_flags.length - 1 ? ' ' : ''}
                </span>
              )
            })}
          </p>
        </div>
      )}
    </div>
  )
}
