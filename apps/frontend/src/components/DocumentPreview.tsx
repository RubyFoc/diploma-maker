import { parseBlocks } from '../utils/renderMarkdownPreview'
import { getHeadingStyle, getPageStyle } from '../utils/institutionPageStyle'
import { PaginatedDocument } from './PaginatedDocument'
import { strings } from '../strings'
import type { InstitutionConfig } from '../types/institution'
import './DocumentPreview.css'
import './DocumentPage.css'

export interface DocumentPreviewProps {
  /** A chapter's accepted content, as plain Markdown-subset text (see `renderMarkdownPreview`). */
  content: string
  /** The project's institution formatting config, if loaded, for page size/font/heading styling. */
  institutionConfig?: InstitutionConfig | null
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
export function DocumentPreview({ content, institutionConfig = null }: DocumentPreviewProps) {
  if (content === '') {
    return <p className="document-preview-empty">{strings.chapterContentEmpty}</p>
  }

  const blocks = parseBlocks(content)
  const pageStyle = getPageStyle(institutionConfig)

  return (
    <div className="document-preview">
      <PaginatedDocument
        blocks={blocks}
        pageStyle={pageStyle}
        headingStyle={(level) => getHeadingStyle(institutionConfig, level)}
        emptyMessage={strings.chapterContentEmpty}
      />
    </div>
  )
}
