import { createContext, useContext, useMemo, useState } from 'react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'

export interface Chapter {
  id: string
  title: string
  content: string
}

export interface DocumentState {
  chapters: Chapter[]
}

export const emptyDocumentState: DocumentState = { chapters: [] }

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
