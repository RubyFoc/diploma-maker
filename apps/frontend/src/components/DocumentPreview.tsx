import { parseBlocks } from '../utils/renderMarkdownPreview'
import { getHeadingStyle, getPageStyle } from '../utils/institutionPageStyle'
import { useChapterLocks } from '../hooks/useChapterLocks'
import { PaginatedDocument } from './PaginatedDocument'
import { strings } from '../strings'
import type { InstitutionConfig } from '../types/institution'
import type { ManifestBlock } from '../types/project'
import './DocumentPreview.css'
import './DocumentPage.css'

export interface DocumentPreviewProps {
  /** A chapter's accepted content, as plain Markdown-subset text (see `renderMarkdownPreview`). */
  content: string
  /** The project's institution formatting config, if loaded, for page size/font/heading styling. */
  institutionConfig?: InstitutionConfig | null
  /** The chapter this content belongs to, and its accepted version's block manifest — both
   * required together to enable the lock-selection UI (TASK-E13-5); omit either to render
   * read-only, e.g. for a chapter with no accepted content yet. */
  chapterId?: string | null
  acceptedManifest?: ManifestBlock[] | null
  /** Currently selected "insert at anchor" block id (TASK-E15-3), if any. Requires `chapterId`/
   * `acceptedManifest` and `onSelectAnchor` together to enable the "insert here" toggle UI. */
  selectedAnchorBlockId?: string | null
  /** Called with the newly selected block's id, or `null` to clear the selection (re-selecting
   * the already-selected block). Omit to render without anchor-selection toggles. */
  onSelectAnchor?: (blockId: string | null) => void
}

/**
 * Live WYSIWYG-ish preview of a chapter's accepted content (TASK-E08-4, TASK-E10-4).
 *
 * Renders `content` as a paginated, institution-styled "paper sheet" via
 * `PaginatedDocument`, matching the page dimensions/font/margins a user would see in the
 * final `.docx` export instead of a raw continuous-scroll text blob. Purely
 * presentational: it re-renders automatically whenever `content` changes (e.g. after an
 * Accept in the diff-viewer flow updates `DocumentContext`'s state), so the preview is
 * "live" for free.
 */
export function DocumentPreview({
  content,
  institutionConfig = null,
  chapterId = null,
  acceptedManifest = null,
  selectedAnchorBlockId = null,
  onSelectAnchor,
}: DocumentPreviewProps) {
  const { lockedBlockIds, toggleLock } = useChapterLocks(chapterId)

  if (content === '') {
    return <p className="document-preview-empty">{strings.chapterContentEmpty}</p>
  }

  const blocks = parseBlocks(content)
  const pageStyle = getPageStyle(institutionConfig)
  const lockSelection =
    chapterId !== null && acceptedManifest !== null
      ? { lockableBlocks: acceptedManifest, lockedBlockIds, onToggleLock: (block: ManifestBlock) => void toggleLock(block) }
      : undefined
  const anchorSelection =
    chapterId !== null && acceptedManifest !== null && onSelectAnchor
      ? {
          anchorableBlocks: acceptedManifest,
          selectedBlockId: selectedAnchorBlockId,
          onSelect: (block: ManifestBlock) =>
            onSelectAnchor(selectedAnchorBlockId === block.id ? null : block.id),
        }
      : undefined

  return (
    <div className="document-preview">
      <PaginatedDocument
        blocks={blocks}
        pageStyle={pageStyle}
        headingStyle={(level) => getHeadingStyle(institutionConfig, level)}
        emptyMessage={strings.chapterContentEmpty}
        lockSelection={lockSelection}
        anchorSelection={anchorSelection}
      />
    </div>
  )
}
