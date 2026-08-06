// Backend API contract types (see docs/architecture for the ADR-0004 versioning model).
// Kept separate from projectService.ts so other modules (contexts, hooks) can import
// the shapes without pulling in fetch logic.

export type ChapterVersionStatus = 'accepted' | 'draft'

// Mirrors the backend's `locks.models.Block` (ADR-0011, TASK-E13-1/2): one lockable block within
// a chapter version's content. Named `ManifestBlock` here (not `Block`) to avoid colliding with
// `utils/renderMarkdownPreview`'s unrelated markdown-rendering `Block` type — see
// `hooks/useChapterLocks.ts` for why the two don't line up block-for-block.
export interface ManifestBlock {
  id: string
  content: string
  content_hash: string
  order: number
}

export interface CharRange {
  start: number
  end: number
}

// Mirrors the backend's `locks.models.Lock` (TASK-E13-4).
export interface Lock {
  id: string
  chapter_id: string
  block_id: string
  block_content_hash: string
  char_range: CharRange | null
  created_at: string
}

export interface ChapterVersion {
  id: string
  chapter_id: string
  version_number: number
  content: string
  manifest: ManifestBlock[] | null
  created_at: string
  status: ChapterVersionStatus
  parent_version_id: string | null
}

export interface ChapterDetail {
  id: string
  project_id: string
  /** `null` for a top-level chapter, another chapter's `id` for a subchapter (ADR-0014, TASK-E12-1/2). */
  parent_chapter_id: string | null
  title: string
  order: number
  created_at: string
  accepted_content: string | null
  /** The accepted version's block manifest (ADR-0011), for lock-selection UI (TASK-E13-5). `null`
   * if there's no accepted version yet, or it predates block manifests. */
  accepted_manifest: ManifestBlock[] | null
  pending_draft: ChapterVersion | null
}

export interface ProjectDetail {
  id: string
  title: string
  created_at: string
  chapters: ChapterDetail[]
}

// Lightweight per-project listing entry backing `GET /projects` (TASK-E11-2/E11-4): no chapters,
// matching the backend's ProjectSummary response model.
export interface ProjectSummary {
  id: string
  title: string
  created_at: string
}

// Mirrors the backend's plagiarism.precheck.PlagiarismCheckResult dataclass, surfaced via the
// generate endpoint's response so the UI can flag a draft for extra review.
export interface PlagiarismSentenceFlag {
  text: string
  plagiarism_score: number
  is_plagiarized: boolean
  is_ai_like: boolean
}

export interface PlagiarismCheckResult {
  plagiarism_score: number
  ai_fingerprint_score: number
  originality_score: number
  flagged: boolean
  reasons: string[]
  sentence_flags: PlagiarismSentenceFlag[]
}

export interface GenerateDraftResult {
  version: ChapterVersion
  precheck: PlagiarismCheckResult
  /** Must-cite sources (TASK-E14) this generation call couldn't ground — see backend
   * `GenerateDraftResponse.unmet_required_sources` for the fail-open rationale. */
  unmet_required_sources: string[]
}

// Mirrors the backend's `sources.required.RequiredSource` (TASK-E14-1).
export interface RequiredSource {
  id: string
  project_id: string
  author: string
  title: string | null
  year: number | null
  created_at: string
}

/** A must-cite author/work entered during onboarding (TASK-E14-4), before any project exists to
 * attach it to — see `DocumentState.pendingRequiredSources`. */
export interface PendingRequiredSource {
  author: string
  title?: string
}
