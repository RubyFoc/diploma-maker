// Mirrors the backend's `history.router` response shapes (ADR-0012, TASK-E16-2/3/4).
import type { ChapterVersion } from './project'

/** Non-content projection of one `history.models.Operation` — see
 * `history.router.OperationSummary`'s docstring for why `before_text`/`after_text`/`applied_by`
 * are deliberately omitted. */
export interface OperationSummary {
  id: string
  block_id: string
  created_at: string
}

/** Response for `GET /chapters/{chapter_id}/operations`: every recorded operation for the
 * chapter, oldest-first, plus where the undo/redo cursor currently sits. */
export interface OperationsListResponse {
  operations: OperationSummary[]
  applied_count: number
  total_operations: number
}

/** Response for both `POST /chapters/{chapter_id}/undo` and `.../redo`. */
export interface UndoRedoResponse {
  version: ChapterVersion
  applied_count: number
  total_operations: number
}
