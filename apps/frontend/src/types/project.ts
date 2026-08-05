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
