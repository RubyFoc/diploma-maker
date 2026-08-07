import type { DocumentState } from '../context/DocumentContext'
import type { ProjectDetail } from '../types/project'

/**
 * Maps the backend ProjectDetail shape onto this app's DocumentState/Chapter shape.
 * `institutionId` is read straight off the project (TASK-INT-17/18: it's now stored per
 * project, not carried over from a prior account-level onboarding selection).
 */
export function toDocumentState(project: ProjectDetail): DocumentState {
  return {
    projectId: project.id,
    institutionId: project.institution_id ?? null,
    title: project.title,
    chapters: project.chapters.map((chapter) => ({
      id: chapter.id,
      title: chapter.title,
      content: chapter.accepted_content ?? '',
      acceptedManifest: chapter.accepted_manifest,
      pendingDraft: chapter.pending_draft,
      streamingContent: null,
      selectedAnchorBlockId: null,
      pendingDraftReroute: null,
    })),
    // Always starts empty: pending required sources (TASK-E14-4) are creation-flow-scoped and
    // either already flushed by `useNewProject` or belong to a project this fetch didn't create.
    pendingRequiredSources: [],
  }
}
