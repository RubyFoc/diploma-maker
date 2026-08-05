import type { DocumentState } from '../context/DocumentContext'
import type { ProjectDetail } from '../types/project'

/** Maps the backend ProjectDetail shape onto this app's DocumentState/Chapter shape. */
export function toDocumentState(project: ProjectDetail): DocumentState {
  return {
    projectId: project.id,
    chapters: project.chapters.map((chapter) => ({
      id: chapter.id,
      title: chapter.title,
      content: chapter.accepted_content ?? '',
      pendingDraft: chapter.pending_draft,
    })),
  }
}
