import { createContext, useContext, useMemo, useState } from 'react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'
import type { ChapterVersion } from '../types/project'

export interface Chapter {
  id: string
  title: string
  content: string
  /** Last draft returned by generateChapterDraft, if any, per ADR-0004. */
  pendingDraft: ChapterVersion | null
}

export interface DocumentState {
  projectId: string | null
  chapters: Chapter[]
}

export const emptyDocumentState: DocumentState = { projectId: null, chapters: [] }

interface DocumentContextValue {
  document: DocumentState
  setDocument: Dispatch<SetStateAction<DocumentState>>
}

const DocumentContext = createContext<DocumentContextValue | undefined>(undefined)

export function DocumentProvider({ children }: { children: ReactNode }) {
  const [document, setDocument] = useState<DocumentState>(emptyDocumentState)
  const value = useMemo(() => ({ document, setDocument }), [document])

  return <DocumentContext.Provider value={value}>{children}</DocumentContext.Provider>
}

export function useDocument(): DocumentContextValue {
  const context = useContext(DocumentContext)
  if (!context) {
    throw new Error('useDocument must be used within a DocumentProvider')
  }
  return context
}
