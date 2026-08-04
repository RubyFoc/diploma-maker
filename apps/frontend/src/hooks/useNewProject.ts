import { useCallback } from 'react'
import { useChat } from '../context/ChatContext'
import { useDocument } from '../context/DocumentContext'
import { createNewProject } from '../services/projectService'

export function useNewProject(): () => Promise<void> {
  const { setDocument } = useDocument()
  const { resetChat } = useChat()

  return useCallback(async () => {
    const project = await createNewProject()
    setDocument(project.document)
    resetChat()
  }, [setDocument, resetChat])
}
