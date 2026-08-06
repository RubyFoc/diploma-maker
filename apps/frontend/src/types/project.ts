// Backend API contract types (see docs/architecture for the ADR-0004 versioning model).
// Kept separate from projectService.ts so other modules (contexts, hooks) can import
// the shapes without pulling in fetch logic.

export type ChapterVersionStatus = 'accepted' | 'draft'

export interface ChapterVersion {
  id: string
  chapter_id: string
  version_number: number
  content: string
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
}
