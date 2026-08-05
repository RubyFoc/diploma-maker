import { renderMarkdownPreview } from '../utils/renderMarkdownPreview'
import { strings } from '../strings'
import './DocumentPreview.css'

export interface DocumentPreviewProps {
  /** A chapter's accepted content, as plain Markdown-subset text (see `renderMarkdownPreview`). */
  content: string
}

/**
 * Live WYSIWYG-ish preview of a chapter's accepted content (TASK-E08-4).
 *
 * Renders `content` as formatted HTML via `renderMarkdownPreview`, matching the structure a
 * user would see in the final `.docx` export, instead of a raw Markdown text blob. Purely
 * presentational: it re-renders automatically whenever `content` changes (e.g. after an Accept
 * in the diff-viewer flow updates `DocumentContext`'s state), so the preview is "live" for free.
 */
export function DocumentPreview({ content }: DocumentPreviewProps) {
  if (content === '') {
    return <p className="document-preview-empty">{strings.chapterContentEmpty}</p>
  }

  return <div className="document-preview">{renderMarkdownPreview(content)}</div>
}
