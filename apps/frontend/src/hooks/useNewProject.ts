import { useCallback } from 'react'
import { useChat } from '../context/ChatContext'
import { useDocument } from '../context/DocumentContext'
import { createProject } from '../services/projectService'
import { toDocumentState } from '../utils/mapProject'

export function useNewProject(): () => Promise<void> {
  const { setDocument } = useDocument()
  const { resetChat } = useChat()

  return useCallback(async () => {
    const project = await createProject()
    setDocument(toDocumentState(project))
    resetChat()
  }, [setDocument, resetChat])
}
