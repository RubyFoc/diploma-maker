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
  /** Active project's university formatting profile id (TASK-INT-17/18), scoped per project —
   * read off the project itself (`toDocumentState`) rather than carried over between projects. */
  institutionId: string | null
  /** Active project's display title, shown in the workspace header; empty until a project is entered. */
  title: string
  chapters: Chapter[]
  /** Must-cite authors/works entered while setting up a new project (TASK-E14-4/TASK-INT-18),
   * before that project exists to attach them to. `useNewProject` submits these against the
   * newly created project and clears the list (via `toDocumentState`'s default) once flushed. */
  pendingRequiredSources: PendingRequiredSource[]
  /** Which chapter or subchapter the next chat instruction generates into (user request: chat
   * generation used to always target `chapters[0]` unconditionally, regardless of which chapter
   * the instruction was actually about, silently writing drafts into the wrong chapter once a
   * project grew past one chapter). `null` before any chapter exists yet, or once one is picked
   * initializes to the first top-level chapter — see `App.tsx`'s `ChatPanel`. Can be a
   * subchapter's id, not just a top-level chapter's, since a subchapter is just a `chapter_id`
   * to the generation endpoints. */
  selectedChatTargetId: string | null
  /** Bumped whenever a chat generation targets a subchapter (`selectedChatTargetId` not among
   * `chapters`), so `App.tsx`'s `SubchaptersList` (which owns its own fetched subchapter state,
   * not part of this context) knows to refetch and pick up the new pending draft — there's no
   * other path for that update to reach it, since subchapters aren't stored here. */
  subchaptersRefreshToken: number
}

export const emptyDocumentState: DocumentState = {
  projectId: null,
  institutionId: null,
  title: '',
  chapters: [],
  pendingRequiredSources: [],
  selectedChatTargetId: null,
  subchaptersRefreshToken: 0,
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
