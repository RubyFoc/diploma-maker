import { emptyChatState } from '../context/ChatContext'
import type { ChatState } from '../context/ChatContext'
import { emptyDocumentState } from '../context/DocumentContext'
import type { DocumentState } from '../context/DocumentContext'

export interface NewProjectResult {
  document: DocumentState
  chat: ChatState
}

// Pure frontend reset until the backend project-creation endpoint exists
// (TASK-E02/E03). Kept as a standalone async function so swapping this body
// for a real API call is a one-function change, not a rewrite of the caller.
export async function createNewProject(): Promise<NewProjectResult> {
  return { document: emptyDocumentState, chat: emptyChatState }
}
