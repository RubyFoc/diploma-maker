import { createContext, useContext, useMemo, useState } from 'react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'
import type { ChapterVersion, ManifestBlock } from '../types/project'

export interface Chapter {
  id: string
  title: string
  content: string
  /** Accepted content's block manifest (ADR-0011), for lock-selection UI (TASK-E13-5). */
  acceptedManifest: ManifestBlock[] | null
  /** Last draft returned by generateChapterDraft, if any, per ADR-0004. */
  pendingDraft: ChapterVersion | null
  /** In-progress SSE draft text while streaming (ADR-0009); null once idle or `pendingDraft` lands. */
  streamingContent: string | null
}

export interface DocumentState {
  projectId: string | null
  /** Selected/uploaded university config's id, per TASK-E10-1 onboarding flow. */
  institutionId: string | null
  /** Active project's display title, shown in the workspace header; empty until a project is entered. */
  title: string
  chapters: Chapter[]
}

export const emptyDocumentState: DocumentState = {
  projectId: null,
  institutionId: null,
  title: '',
  chapters: [],
}

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
