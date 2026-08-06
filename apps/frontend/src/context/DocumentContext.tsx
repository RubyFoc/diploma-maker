import { createContext, useContext, useMemo, useState } from 'react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'
import type { ChapterVersion, ManifestBlock, PendingRequiredSource } from '../types/project'

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
  /** Block chosen via `DocumentPreview`'s "insert here" toggle (TASK-E15-3) as the anchor for the
   * next chat instruction's "insert at anchor" generation. Cleared once that generation starts
   * (see `App.tsx`'s `ChatPanel.handleSend`). `null` means the next instruction generates the
   * whole chapter, as before E15. */
  selectedAnchorBlockId: string | null
  /** Set alongside `pendingDraft` when the backend rerouted an anchor-mode generation away from
   * a locked `target_block_id` (TASK-E15-2/3, ADR-0011) — `null` for full-chapter drafts and for
   * anchor-mode drafts that landed on the requested block. Cleared whenever `pendingDraft` is. */
  pendingDraftReroute: { requestedBlockId: string; usedBlockId: string } | null
}

export interface DocumentState {
  projectId: string | null
  /** Selected/uploaded university config's id, per TASK-E10-1 onboarding flow. */
  institutionId: string | null
  /** Active project's display title, shown in the workspace header; empty until a project is entered. */
  title: string
  chapters: Chapter[]
  /** Must-cite authors/works entered during onboarding (TASK-E14-4), before any project exists
   * to attach them to. `useNewProject` submits these against the newly created project and
   * clears the list (via `toDocumentState`'s default) once flushed. */
  pendingRequiredSources: PendingRequiredSource[]
}

export const emptyDocumentState: DocumentState = {
  projectId: null,
  institutionId: null,
  title: '',
  chapters: [],
  pendingRequiredSources: [],
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
