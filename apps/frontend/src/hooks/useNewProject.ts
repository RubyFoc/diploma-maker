import { useCallback } from 'react'
import { useChat } from '../context/ChatContext'
import { useDocument } from '../context/DocumentContext'
import { createProject } from '../services/projectService'
import { createRequiredSource } from '../services/requiredSourcesService'
import { toDocumentState } from '../utils/mapProject'

export function useNewProject(): () => Promise<void> {
  const { document: doc, setDocument } = useDocument()
  const { resetChat } = useChat()

  return useCallback(async () => {
    const project = await createProject()
    // Flush any must-cite sources entered during onboarding (TASK-E14-4) against the newly
    // created project. Best-effort per source: one failing (e.g. a transient network error)
    // shouldn't stop the others or block entering the new project.
    await Promise.all(
      doc.pendingRequiredSources.map((source) =>
        createRequiredSource(project.id, source.author, source.title).catch(() => {}),
      ),
    )
    setDocument((previous) => toDocumentState(project, previous.institutionId))
    resetChat()
  }, [doc.pendingRequiredSources, setDocument, resetChat])
}
