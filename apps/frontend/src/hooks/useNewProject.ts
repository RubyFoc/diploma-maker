import { useCallback } from 'react'
import { useChat } from '../context/ChatContext'
import { useDocument } from '../context/DocumentContext'
import { createProject } from '../services/projectService'
import { createRequiredSource } from '../services/requiredSourcesService'
import { toDocumentState } from '../utils/mapProject'

export function useNewProject(): (institutionId?: string | null) => Promise<void> {
  const { document: doc, setDocument } = useDocument()
  const { resetChat } = useChat()

  return useCallback(
    async (institutionId: string | null = null) => {
      const project = await createProject(undefined, institutionId)
      // Flush any must-cite sources entered during the new-project setup flow (TASK-E14-4/
      // TASK-INT-18) against the newly created project. Best-effort per source: one failing
      // (e.g. a transient network error) shouldn't stop the others or block entering the project.
      await Promise.all(
        doc.pendingRequiredSources.map((source) =>
          createRequiredSource(project.id, source.author, source.title).catch(() => {}),
        ),
      )
      setDocument(() => toDocumentState(project))
      resetChat()
    },
    [doc.pendingRequiredSources, setDocument, resetChat],
  )
}
