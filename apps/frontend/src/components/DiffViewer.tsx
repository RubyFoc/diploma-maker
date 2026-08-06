import type { ReactNode } from 'react'
import { diffLines } from '../utils/diff'
import type { DiffSegmentType } from '../utils/diff'
import { parseBlocks, renderBlock } from '../utils/renderMarkdownPreview'
import type { Block } from '../utils/renderMarkdownPreview'
import { getHeadingStyle, getPageStyle } from '../utils/institutionPageStyle'
import { PaginatedDocument } from './PaginatedDocument'
import { strings } from '../strings'
import type { InstitutionConfig } from '../types/institution'
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
}: DiffViewerProps) {
  const taggedBlocks = buildTaggedBlocks(before, after)
  const pageStyle = getPageStyle(institutionConfig)

  const renderDiffBlock = (block: Block, key: number): ReactNode => {
    const segmentType = taggedBlocks[key]?.segmentType ?? 'unchanged'
    return (
      <span key={key} className={`diff-inline diff-${segmentType}`} data-testid={`diff-segment-${segmentType}`}>
        {renderBlock(block, key)}
      </span>
    )
  }

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
        />
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
