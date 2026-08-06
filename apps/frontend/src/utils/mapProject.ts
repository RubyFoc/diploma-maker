import type { DocumentState } from '../context/DocumentContext'
import type { ProjectDetail } from '../types/project'

/**
 * Maps the backend ProjectDetail shape onto this app's DocumentState/Chapter shape.
 * `institutionId` isn't part of ProjectDetail, so callers pass through the previous
 * value (e.g. `setDocument((previous) => toDocumentState(project, previous.institutionId))`)
 * to avoid losing the onboarding-selected institution on refetch/new-project.
 */
export function toDocumentState(project: ProjectDetail, institutionId: string | null = null): DocumentState {
  return {
    projectId: project.id,
    institutionId,
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
    // Always starts empty: pending required sources (TASK-E14-4) are onboarding-scoped and
    // either already flushed by `useNewProject` or belong to a project this fetch didn't create.
    pendingRequiredSources: [],
  }
}
