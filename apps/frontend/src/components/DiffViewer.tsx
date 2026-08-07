import { useState } from 'react'
import type { ReactNode } from 'react'
import { diffLines } from '../utils/diff'
import type { DiffSegmentType } from '../utils/diff'
import { parseBlocks, renderBlock } from '../utils/renderMarkdownPreview'
import type { Block } from '../utils/renderMarkdownPreview'
import { getHeadingStyle, getPageStyle } from '../utils/institutionPageStyle'
import { resolvePageRedoCount, resolvePageUndoCount } from '../utils/resolvePageRevertCount'
import { PaginatedDocument } from './PaginatedDocument'
import { strings } from '../strings'
import type { InstitutionConfig } from '../types/institution'
import type { OperationSummary } from '../types/history'
import type { ManifestBlock } from '../types/project'
import './DiffViewer.css'
import './DocumentPage.css'

export interface DiffViewerProps {
  /** Current accepted version content. */
  before: string
  /** Pending draft version content, per ADR-0004. */
  after: string
  /** Called when the user accepts the draft. Caller owns any API/state update. */
  onAccept: () => void
  /** Called when the user rejects the draft. Caller owns any API/state update. */
  onReject: () => void
  /** The project's institution formatting config, if loaded, for page size/font/heading styling. */
  institutionConfig?: InstitutionConfig | null
  /** Set when this pending draft was generated in "insert at anchor" mode (TASK-E15-1) and the
   * requested anchor was locked, so the backend deterministically rerouted to a different
   * unlocked block (TASK-E15-2, ADR-0011). `null`/omitted renders no banner — full-chapter
   * drafts and anchor-mode drafts that landed on the requested block both fall here. Deliberately
   * not the raw API response shape (`used_block_id`/`rerouted_from_block_id`), per this
   * component's presentational-only contract. */
  rerouteNotice?: { requestedBlockId: string; usedBlockId: string } | null
  /** The pending draft's own block manifest (ADR-0011), for resolving "undo/redo this page"
   * (TASK-E16-4) into a block-id set for whichever page is currently visible. Matched
   * positionally against this draft's content the same approximate way
   * `PaginatedDocument`'s `lockSelection.lockableBlocks` is — see that component's doc comment.
   * Omit (along with `history`) to hide the undo/redo controls entirely. */
  manifest?: ManifestBlock[] | null
  /** This chapter's undo/redo op-log position (TASK-E16-2/3/4), fetched by the caller (e.g. via
   * `hooks/useChapterHistory`). `null` hides the controls — the common case for a chapter that
   * has never used anchor-mode generation, per that hook's doc comment — as does a non-null
   * `totalOperations === 0`. */
  history?: { operations: OperationSummary[]; appliedCount: number; totalOperations: number } | null
  /** Distinct message to show after a failed undo/redo attempt (TASK-E16-5): `'conflict'` for a
   * 409 (a race, or a vanished anchor block), `'generic'` otherwise. `null` shows nothing. */
  historyError?: 'conflict' | 'generic' | null
  /** Called with the resolved step count for whichever undo control was clicked. Caller owns the
   * actual API call (this component has no knowledge of APIs, per its doc comment) and updating
   * the draft afterwards. */
  onUndo?: (count: number) => void
  onRedo?: (count: number) => void
}

interface TaggedBlock {
  block: Block
  segmentType: DiffSegmentType
}

/**
 * Re-parses each diff segment's raw lines back into `Block`s (headings/lists/bold, not
 * literal Markdown syntax) and tags every resulting block with the segment type it came
 * from, so the combined sequence can be paginated and rendered like one document instead
 * of one `<p>` per segment.
 */
function buildTaggedBlocks(before: string, after: string): TaggedBlock[] {
  const segments = diffLines(before, after)
  const tagged: TaggedBlock[] = []
  for (const segment of segments) {
    for (const block of parseBlocks(segment.lines.join('\n'))) {
      tagged.push({ block, segmentType: segment.type })
    }
  }
  return tagged
}

/**
 * Presentational diff viewer for a pending draft version (TASK-E08-2, TASK-E10-4).
 *
 * Renders the line-based diff between `before` and `after` (see `utils/diff.ts`) as
 * Word-style tracked changes — inline colored underline (additions) / strikethrough
 * (removals) text within a paginated, institution-styled page — plus Accept/Reject
 * controls. This component has no knowledge of versions, chapters, or APIs — it only
 * diffs two strings and calls back to whatever the caller wires up (matching the
 * hook/service split used by `useNewProject`/`projectService.ts`).
 *
 * Deliberately does NOT wire `PaginatedDocument`'s `lockSelection` prop (TASK-E13-5): locks
 * anchor only to the chapter's current *accepted* content (ADR-0011, `locks.service.lock_block`),
 * and this view mixes that accepted content with a still-pending, possibly-to-be-rejected draft
 * — a block a user might select here isn't a stable target to lock against. `DocumentPreview`
 * (rendering the accepted content on its own) is where lock selection lives.
 */
export function DiffViewer({
  before,
  after,
  onAccept,
  onReject,
  institutionConfig = null,
  rerouteNotice = null,
  manifest = null,
  history = null,
  historyError = null,
  onUndo,
  onRedo,
}: DiffViewerProps) {
  const taggedBlocks = buildTaggedBlocks(before, after)
  const pageStyle = getPageStyle(institutionConfig)
  const [visiblePageBlockIds, setVisiblePageBlockIds] = useState<string[]>([])
  // Arms the "this page" undo/redo button once `spansOtherEdits` is true, so `widerCount` (which
  // also reverts/reapplies unrelated operations elsewhere) is never sent on the first click — the
  // user must explicitly confirm, mirroring `ProjectLanding`'s `confirmingDeleteId` two-click
  // pattern for its own destructive action.
  const [pendingWiderConfirm, setPendingWiderConfirm] = useState<'undo' | 'redo' | null>(null)

  const renderDiffBlock = (block: Block, key: number): ReactNode => {
    const segmentType = taggedBlocks[key]?.segmentType ?? 'unchanged'
    return (
      <span key={key} className={`diff-inline diff-${segmentType}`} data-testid={`diff-segment-${segmentType}`}>
        {renderBlock(block, key)}
      </span>
    )
  }

  // Maps each tagged block back to the after-content's manifest block id (TASK-E16-4): 'removed'
  // segments only exist in `before`, so they have no counterpart in `manifest` (the pending
  // draft's own block list) — every other segment, in order, lines up with the next manifest
  // entry. Anchor-mode generation (the only path that ever records undo-able operations) never
  // removes content, so in practice this covers every operation-bearing draft exactly.
  //
  // Same positional-matching caveat as `PaginatedDocument`'s `lockSelection.lockableBlocks` doc
  // comment (see that component): the manifest has one entry per source *line*, but `parseBlocks`
  // collapses consecutive markdown list items into a single rendered block, so if anchor-inserted
  // content contains a list, the mapping can drift for blocks after it. Left as a known
  // limitation for now (not fixed here) — a mismatch only affects which page a list's own undo/
  // redo controls attribute it to, not the correctness of the underlying undo/redo op-log itself.
  let afterIndex = 0
  const pageBlockIds: (string | null)[] | undefined = manifest
    ? taggedBlocks.map((tagged) => {
        if (tagged.segmentType === 'removed') {
          return null
        }
        const id = manifest[afterIndex]?.id ?? null
        afterIndex += 1
        return id
      })
    : undefined

  const pageBlockIdSet = new Set(visiblePageBlockIds)
  const hasHistory = history !== null && history.totalOperations > 0
  const undoPage = hasHistory ? resolvePageUndoCount(history.operations, history.appliedCount, pageBlockIdSet) : null
  const redoPage = hasHistory ? resolvePageRedoCount(history.operations, history.appliedCount, pageBlockIdSet) : null

  return (
    <section className="diff-viewer" aria-label={strings.diffViewerTitle}>
      <h3>{strings.diffViewerTitle}</h3>
      {rerouteNotice && (
        <p className="diff-reroute-notice" role="status">
          {strings.diffRerouteNoticeMessage}
        </p>
      )}
      {taggedBlocks.length === 0 ? (
        <p>{strings.diffEmpty}</p>
      ) : (
        <PaginatedDocument
          blocks={taggedBlocks.map((tagged) => tagged.block)}
          pageStyle={pageStyle}
          headingStyle={(level) => getHeadingStyle(institutionConfig, level)}
          renderBlock={renderDiffBlock}
          pageBlockIds={pageBlockIds}
          onPageBlockIdsChange={pageBlockIds ? setVisiblePageBlockIds : undefined}
        />
      )}
      {hasHistory && history && (
        <div className="diff-history-controls" aria-label={strings.historyControlsTitle}>
          {historyError && (
            <p className="diff-history-error" role="alert">
              {historyError === 'conflict' ? strings.historyConflictErrorMessage : strings.historyGenericErrorMessage}
            </p>
          )}
          <div className="diff-history-actions">
            <button
              type="button"
              disabled={history.appliedCount === 0}
              onClick={() => onUndo?.(1)}
            >
              {strings.historyUndoLastButton}
            </button>
            <button
              type="button"
              disabled={history.appliedCount === history.totalOperations}
              onClick={() => onRedo?.(1)}
            >
              {strings.historyRedoLastButton}
            </button>
            {pendingWiderConfirm === 'undo' && undoPage ? (
              <>
                <button
                  type="button"
                  onClick={() => {
                    onUndo?.(undoPage.widerCount)
                    setPendingWiderConfirm(null)
                  }}
                >
                  {strings.historyPageUndoConfirmButton(undoPage.otherEditsCount)}
                </button>
                <button type="button" onClick={() => setPendingWiderConfirm(null)}>
                  {strings.historyPageRevertCancelButton}
                </button>
              </>
            ) : (
              <button
                type="button"
                disabled={!undoPage || undoPage.count === 0}
                onClick={() => {
                  if (!undoPage) {
                    return
                  }
                  if (undoPage.spansOtherEdits) {
                    setPendingWiderConfirm('undo')
                    return
                  }
                  onUndo?.(undoPage.count)
                }}
              >
                {strings.historyUndoPageButton}
              </button>
            )}
            {pendingWiderConfirm === 'redo' && redoPage ? (
              <>
                <button
                  type="button"
                  onClick={() => {
                    onRedo?.(redoPage.widerCount)
                    setPendingWiderConfirm(null)
                  }}
                >
                  {strings.historyPageRedoConfirmButton(redoPage.otherEditsCount)}
                </button>
                <button type="button" onClick={() => setPendingWiderConfirm(null)}>
                  {strings.historyPageRevertCancelButton}
                </button>
              </>
            ) : (
              <button
                type="button"
                disabled={!redoPage || redoPage.count === 0}
                onClick={() => {
                  if (!redoPage) {
                    return
                  }
                  if (redoPage.spansOtherEdits) {
                    setPendingWiderConfirm('redo')
                    return
                  }
                  onRedo?.(redoPage.count)
                }}
              >
                {strings.historyRedoPageButton}
              </button>
            )}
            <button
              type="button"
              disabled={history.appliedCount === 0}
              onClick={() => onUndo?.(history.appliedCount)}
            >
              {strings.historyUndoAllButton}
            </button>
            <button
              type="button"
              disabled={history.appliedCount === history.totalOperations}
              onClick={() => onRedo?.(history.totalOperations - history.appliedCount)}
            >
              {strings.historyRedoAllButton}
            </button>
          </div>
          {undoPage?.spansOtherEdits && (
            <p className="diff-history-warning" role="status">
              {strings.historyPageRevertSpansWarning(undoPage.otherEditsCount)}
            </p>
          )}
          {redoPage?.spansOtherEdits && (
            <p className="diff-history-warning" role="status">
              {strings.historyPageRedoSpansWarning(redoPage.otherEditsCount)}
            </p>
          )}
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
