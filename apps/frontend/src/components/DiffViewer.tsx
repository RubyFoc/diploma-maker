import { diffLines } from '../utils/diff'
import { strings } from '../strings'
import './DiffViewer.css'

export interface DiffViewerProps {
  /** Current accepted version content. */
  before: string
  /** Pending draft version content, per ADR-0004. */
  after: string
  /** Called when the user accepts the draft. Caller owns any API/state update. */
  onAccept: () => void
  /** Called when the user rejects the draft. Caller owns any API/state update. */
  onReject: () => void
}

/**
 * Presentational diff viewer for a pending draft version (TASK-E08-2).
 *
 * Renders the line-based diff between `before` and `after` (see
 * `utils/diff.ts`) with added/removed/unchanged segments visually
 * distinguished, plus Accept/Reject controls. This component has no
 * knowledge of versions, chapters, or APIs — it only diffs two strings and
 * calls back to whatever the caller wires up (matching the
 * hook/service split used by `useNewProject`/`projectService.ts`).
 */
export function DiffViewer({ before, after, onAccept, onReject }: DiffViewerProps) {
  const segments = diffLines(before, after)

  return (
    <section className="diff-viewer" aria-label={strings.diffViewerTitle}>
      <h3>{strings.diffViewerTitle}</h3>
      {segments.length === 0 ? (
        <p>{strings.diffEmpty}</p>
      ) : (
        <div className="diff-segments">
          {segments.map((segment, index) => (
            <p key={index} className={`diff-segment diff-segment--${segment.type}`} data-testid={`diff-segment-${segment.type}`}>
              {segment.lines.join('\n')}
            </p>
          ))}
        </div>
      )}
      <div className="diff-actions">
        <button type="button" className="diff-accept" onClick={onAccept}>
          {strings.diffAcceptButton}
        </button>
        <button type="button" className="diff-reject" onClick={onReject}>
          {strings.diffRejectButton}
        </button>
      </div>
    </section>
  )
}
