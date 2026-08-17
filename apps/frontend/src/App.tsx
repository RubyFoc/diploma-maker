import { useEffect, useState } from 'react'
import './App.css'
import { AuthProvider, emptyAuthState, useAuth } from './context/AuthContext'
import { ChatProvider, useChat } from './context/ChatContext'
import { DocumentProvider, emptyDocumentState, useDocument } from './context/DocumentContext'
import { useInstitutionConfig } from './hooks/useInstitutionConfig'
import { strings } from './strings'
import { DiffViewer } from './components/DiffViewer'
import { DocumentPreview } from './components/DocumentPreview'
import { Onboarding } from './components/Onboarding'
import { PlagiarismCheckPanel } from './components/PlagiarismCheckPanel'
import { ProjectLanding } from './components/ProjectLanding'
import { useChapterHistory } from './hooks/useChapterHistory'
import { exportProject } from './services/exportService'
import { recordSignal } from './services/feedbackService'
import {
  RequestError,
  acceptDraft,
  createChapter,
  generateChapterDraft,
  getProject,
  uploadChapterDraft,
  uploadDocument,
  uploadToc,
} from './services/projectService'
import { streamChapterDraft } from './services/generateStream'
import { toDocumentState } from './utils/mapProject'
import type { Chapter } from './context/DocumentContext'
import type { InstitutionConfig } from './types/institution'
import type { ChapterVersion } from './types/project'

function ChatPanel() {
  const { chat, appendMessage } = useChat()
  const { document: doc, setDocument } = useDocument()
  const [inputValue, setInputValue] = useState('')
  const [isSending, setIsSending] = useState(false)

  const setChapterStreamingContent = (chapterId: string, streamingContent: string | null) => {
    setDocument((previous) => ({
      ...previous,
      chapters: previous.chapters.map((existing) =>
        existing.id === chapterId ? { ...existing, streamingContent } : existing,
      ),
    }))
  }

  const clearChapterAnchor = (chapterId: string) => {
    setDocument((previous) => ({
      ...previous,
      chapters: previous.chapters.map((existing) =>
        existing.id === chapterId ? { ...existing, selectedAnchorBlockId: null } : existing,
      ),
    }))
  }

  const anchorChapter = doc.chapters[0]
  const selectedAnchorBlockId = anchorChapter?.selectedAnchorBlockId ?? null

  const handleSend = async () => {
    const text = inputValue.trim()
    const projectId = doc.projectId
    if (text === '' || projectId === null || isSending) {
      return
    }

    setInputValue('')
    setIsSending(true)
    appendMessage({ id: crypto.randomUUID(), role: 'user', text })

    try {
      let chapter = doc.chapters[0]
      if (!chapter) {
        const created = await createChapter(projectId, strings.defaultChapterTitle)
        chapter = {
          id: created.id,
          title: created.title,
          content: created.accepted_content ?? '',
          acceptedManifest: created.accepted_manifest,
          pendingDraft: created.pending_draft,
          streamingContent: null,
          selectedAnchorBlockId: null,
          pendingDraftReroute: null,
        }
        setDocument((previous) => ({ ...previous, chapters: [...previous.chapters, chapter] }))
      }

      const chapterId = chapter.id
      // "Insert at anchor" mode (TASK-E15-1/3): a block was selected via the "insert here"
      // toggle in DocumentPreview. Clear the selection now — before generation starts, per this
      // task's spec — rather than only on accept/reject, so a stale selection can't silently
      // reapply to an unrelated follow-up instruction.
      const anchorBlockId = chapter.selectedAnchorBlockId
      if (anchorBlockId !== null) {
        clearChapterAnchor(chapterId)
      }

      if (anchorBlockId !== null) {
        try {
          const result = await generateChapterDraft(projectId, chapterId, text, anchorBlockId)
          setDocument((previous) => ({
            ...previous,
            chapters: previous.chapters.map((existing) =>
              existing.id === chapterId
                ? {
                    ...existing,
                    pendingDraft: result.version,
                    pendingDraftReroute: result.rerouted_from_block_id
                      ? { requestedBlockId: result.rerouted_from_block_id, usedBlockId: result.used_block_id ?? '' }
                      : null,
                    streamingContent: null,
                  }
                : existing,
            ),
          }))
          appendMessage({
            id: crypto.randomUUID(),
            role: 'assistant',
            text: result.precheck.flagged ? strings.chatDraftFlaggedMessage : strings.chatDraftReadyMessage,
          })
          void getProject(projectId)
            .then((project) => {
              setDocument((previous) => ({ ...previous, title: project.title }))
            })
            .catch(() => {})
        } catch (error) {
          const message =
            error instanceof RequestError && error.status === 409
              ? strings.chatChapterFullyLockedMessage
              : strings.chatGenerationErrorMessage
          appendMessage({ id: crypto.randomUUID(), role: 'assistant', text: message })
        }
        return
      }

      let streamedText = ''
      setChapterStreamingContent(chapterId, '')

      await new Promise<void>((resolve) => {
        const cleanup = streamChapterDraft(projectId, chapterId, text, {
          onToken: (chunk) => {
            streamedText += chunk
            setChapterStreamingContent(chapterId, streamedText)
          },
          onDone: ({ version: draft, precheck }) => {
            setDocument((previous) => ({
              ...previous,
              chapters: previous.chapters.map((existing) =>
                existing.id === chapterId
                  ? { ...existing, pendingDraft: draft, pendingDraftReroute: null, streamingContent: null }
                  : existing,
              ),
            }))
            appendMessage({
              id: crypto.randomUUID(),
              role: 'assistant',
              text: precheck.flagged ? strings.chatDraftFlaggedMessage : strings.chatDraftReadyMessage,
            })
            // Server-side generation may retitle the project from its default (e.g. via an
            // LLM-derived title from the user's first instruction) — refetch rather than guess
            // the new title client-side. Best-effort, mirrors the recordSignal fire-and-forget
            // pattern in DocumentPanel.
            void getProject(projectId)
              .then((project) => {
                setDocument((previous) => ({ ...previous, title: project.title }))
              })
              .catch(() => {})
            cleanup()
            resolve()
          },
          onError: () => {
            setChapterStreamingContent(chapterId, null)
            appendMessage({ id: crypto.randomUUID(), role: 'assistant', text: strings.chatGenerationErrorMessage })
            cleanup()
            resolve()
          },
        })
      })
    } catch {
      appendMessage({ id: crypto.randomUUID(), role: 'assistant', text: strings.chatGenerationErrorMessage })
    } finally {
      setIsSending(false)
    }
  }

  return (
    <section className="panel chat-panel" aria-label={strings.chatPanelTitle}>
      <h2>{strings.chatPanelTitle}</h2>
      <div className="chat-messages">
        {chat.messages.length === 0 ? (
          <p className="chat-empty">{strings.chatEmpty}</p>
        ) : (
          chat.messages.map((message) => (
            <div key={message.id} className={`chat-message chat-message--${message.role}`}>
              <strong>{message.role}</strong>
              <span>{message.text}</span>
            </div>
          ))
        )}
      </div>
      {selectedAnchorBlockId !== null && anchorChapter && (
        <div className="chat-anchor-indicator">
          <span>{strings.chatInsertingAtIndicator}</span>
          <button type="button" onClick={() => clearChapterAnchor(anchorChapter.id)}>
            {strings.chatCancelInsertionPointButton}
          </button>
        </div>
      )}
      <form
        className="chat-form"
        onSubmit={(event) => {
          event.preventDefault()
          void handleSend()
        }}
      >
        <input
          type="text"
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          placeholder={strings.chatInputPlaceholder}
          aria-label={strings.chatInputPlaceholder}
          disabled={doc.projectId === null || isSending}
        />
        <button type="submit" disabled={doc.projectId === null || isSending}>
          {strings.chatSendButton}
        </button>
      </form>
    </section>
  )
}

/**
 * Renders one chapter's pending-draft diff plus its undo/redo controls (TASK-E16-4/5). Split out
 * of `DocumentPanel`'s chapter list so `useChapterHistory` (which fetches the chapter's op-log)
 * can be called once per chapter, rather than conditionally inside a `.map` — `chapterId` is only
 * ever non-null here while `pendingDraft` exists, since undo/redo only matter for a chapter whose
 * draft is currently on screen.
 */
function ChapterDraftDiff({
  chapter,
  institutionConfig,
  onAccept,
  onReject,
  onDraftUpdated,
}: {
  chapter: Chapter
  institutionConfig: InstitutionConfig | null
  onAccept: () => void
  onReject: () => void
  onDraftUpdated: (version: ChapterVersion) => void
}) {
  const { pendingDraft } = chapter
  const { history, error: historyError, undo, redo } = useChapterHistory(
    pendingDraft ? chapter.id : null,
    onDraftUpdated,
    pendingDraft?.id,
  )

  if (!pendingDraft) {
    return null
  }

  return (
    <DiffViewer
      before={chapter.content}
      after={pendingDraft.content}
      onAccept={onAccept}
      onReject={onReject}
      institutionConfig={institutionConfig}
      rerouteNotice={chapter.pendingDraftReroute}
      manifest={pendingDraft.manifest}
      history={
        history
          ? { operations: history.operations, appliedCount: history.applied_count, totalOperations: history.total_operations }
          : null
      }
      historyError={historyError}
      onUndo={(count) => void undo(count)}
      onRedo={(count) => void redo(count)}
    />
  )
}

/**
 * Lets the user upload their whole already-written document in one go (user request: uploading
 * one chapter at a time doesn't scale to a mostly- or fully-written thesis). Splits the document
 * by `Heading 1` paragraph into chapters, each with its content pre-filled as a pending draft to
 * review — combining what `TocUploadForm` (titles only) and per-chapter draft upload used to
 * require as two separate steps.
 */
function DocumentUploadForm() {
  const { document: doc, setDocument } = useDocument()
  const [file, setFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState(false)

  const handleUpload = async () => {
    const projectId = doc.projectId
    if (projectId === null || file === null || isUploading) {
      return
    }
    setIsUploading(true)
    setError(false)
    try {
      const project = await uploadDocument(projectId, file)
      setDocument(() => toDocumentState(project))
      setFile(null)
    } catch {
      setError(true)
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="document-upload-section">
      <h3>{strings.documentUploadTitle}</h3>
      <p className="document-panel-hint">{strings.documentUploadSubtitle}</p>
      <form
        className="document-upload-form"
        onSubmit={(event) => {
          event.preventDefault()
          void handleUpload()
        }}
      >
        <label>
          {strings.documentUploadLabel}
          <input type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        </label>
        <button type="submit" disabled={file === null || isUploading}>
          {isUploading ? strings.documentUploadButtonPending : strings.documentUploadButton}
        </button>
        {error && <p className="document-panel-error">{strings.documentUploadErrorMessage}</p>}
      </form>
    </div>
  )
}

/**
 * Lets the user upload a `.docx` table of contents (TASK-E10-2/E10-3) so one chapter gets
 * created per entry, in order, instead of relying solely on the chat flow to create chapters
 * one at a time. Shown alongside `DocumentUploadForm` for the titles-only case (no content yet
 * to bring in).
 */
function TocUploadForm() {
  const { document: doc, setDocument } = useDocument()
  const [file, setFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState(false)

  const handleUpload = async () => {
    const projectId = doc.projectId
    if (projectId === null || file === null || isUploading) {
      return
    }
    setIsUploading(true)
    setError(false)
    try {
      const project = await uploadToc(projectId, file)
      setDocument(() => toDocumentState(project))
      setFile(null)
    } catch {
      setError(true)
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="toc-upload-section">
      <h3>{strings.tocUploadTitle}</h3>
      <p className="document-panel-hint">{strings.tocUploadSubtitle}</p>
      <form
        className="toc-upload-form"
        onSubmit={(event) => {
          event.preventDefault()
          void handleUpload()
        }}
      >
        <label>
          {strings.tocUploadLabel}
          <input type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        </label>
        <button type="submit" disabled={file === null || isUploading}>
          {isUploading ? strings.tocUploadButtonPending : strings.tocUploadButton}
        </button>
        {error && <p className="document-panel-error">{strings.tocUploadErrorMessage}</p>}
      </form>
    </div>
  )
}

/**
 * Lets the user upload their own already-written `.docx`/`.pdf` draft for a chapter (TASK-E13-3)
 * instead of only ever generating one via chat. The upload becomes a pending draft version, so
 * it goes through the same `DiffViewer` accept/reject flow as an AI-generated draft.
 */
function ChapterDraftUploadForm({
  chapterId,
  onUploaded,
}: {
  chapterId: string
  onUploaded: (version: ChapterVersion) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState(false)

  const handleUpload = async () => {
    if (file === null || isUploading) {
      return
    }
    setIsUploading(true)
    setError(false)
    try {
      const version = await uploadChapterDraft(chapterId, file)
      onUploaded(version)
      setFile(null)
    } catch {
      setError(true)
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <form
      className="chapter-draft-upload-form"
      onSubmit={(event) => {
        event.preventDefault()
        void handleUpload()
      }}
    >
      <label>
        {strings.chapterDraftUploadLabel}
        <input type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
      </label>
      <button type="submit" disabled={file === null || isUploading}>
        {isUploading ? strings.chapterDraftUploadButtonPending : strings.chapterDraftUploadButton}
      </button>
      {error && <p className="document-panel-error">{strings.chapterDraftUploadErrorMessage}</p>}
    </form>
  )
}

function DocumentPanel() {
  const { document: doc, setDocument } = useDocument()
  const { config: institutionConfig } = useInstitutionConfig(doc.institutionId)

  const handleAccept = async (chapterId: string, draftId: string) => {
    await acceptDraft(draftId)
    if (doc.institutionId !== null) {
      void recordSignal(doc.institutionId, chapterId, draftId, 'approve').catch(() => {})
    }
    if (doc.projectId !== null) {
      const project = await getProject(doc.projectId)
      setDocument(() => toDocumentState(project))
      return
    }
    setDocument((previous) => ({
      ...previous,
      chapters: previous.chapters.map((chapter) =>
        chapter.id === chapterId ? { ...chapter, pendingDraft: null, pendingDraftReroute: null } : chapter,
      ),
    }))
  }

  const handleReject = (chapterId: string, draftId: string) => {
    if (doc.institutionId !== null) {
      void recordSignal(doc.institutionId, chapterId, draftId, 'reject').catch(() => {})
    }
    setDocument((previous) => ({
      ...previous,
      chapters: previous.chapters.map((chapter) =>
        chapter.id === chapterId ? { ...chapter, pendingDraft: null, pendingDraftReroute: null } : chapter,
      ),
    }))
  }

  const setChapterAnchor = (chapterId: string, blockId: string | null) => {
    setDocument((previous) => ({
      ...previous,
      chapters: previous.chapters.map((chapter) =>
        chapter.id === chapterId ? { ...chapter, selectedAnchorBlockId: blockId } : chapter,
      ),
    }))
  }

  // Undo/redo (TASK-E16-4/5) mutate the chapter's pending draft in place — same `id`/
  // `version_number`, only `content`/`manifest` change — so this just swaps in the returned
  // version, mirroring how `handleAccept`/`handleReject` already update `pendingDraft`.
  const handleDraftUpdated = (chapterId: string, version: ChapterVersion) => {
    setDocument((previous) => ({
      ...previous,
      chapters: previous.chapters.map((chapter) =>
        chapter.id === chapterId ? { ...chapter, pendingDraft: version } : chapter,
      ),
    }))
  }

  return (
    <section className="panel document-panel" aria-label={strings.documentPanelTitle}>
      <h2>{strings.documentPanelTitle}</h2>
      <DocumentUploadForm />
      <TocUploadForm />
      {doc.chapters.length === 0 ? (
        <p className="document-empty">{strings.documentEmpty}</p>
      ) : (
        <ul className="chapter-list">
          {doc.chapters.map((chapter, index) => {
            const { pendingDraft, streamingContent } = chapter
            // ChatPanel.handleSend only ever generates into doc.chapters[0] (there is no
            // chapter-picker concept yet), so the "insert here" toggle must only be offered
            // there too — otherwise a selection on any other chapter would be inert.
            const isChatTargetChapter = index === 0
            return (
              <li key={chapter.id} className="chapter-item">
                <h3>{chapter.title}</h3>
                <DocumentPreview
                  content={chapter.content}
                  institutionConfig={institutionConfig}
                  chapterId={chapter.id}
                  acceptedManifest={chapter.acceptedManifest}
                  selectedAnchorBlockId={chapter.selectedAnchorBlockId}
                  onSelectAnchor={isChatTargetChapter ? (blockId) => setChapterAnchor(chapter.id, blockId) : undefined}
                />
                {/* Live SSE preview (ADR-0009): shown while tokens are still arriving, before
                    `pendingDraft`/`DiffViewer` take over once `done` fires. Reuses
                    `DocumentPreview` rather than a new component since it already renders
                    arbitrary chapter text and re-renders live as `streamingContent` grows. */}
                {streamingContent !== null && !pendingDraft && (
                  <div className="chapter-streaming" aria-label={strings.chapterStreamingLabel}>
                    <DocumentPreview content={streamingContent} institutionConfig={institutionConfig} />
                  </div>
                )}
                {pendingDraft && (
                  <ChapterDraftDiff
                    chapter={chapter}
                    institutionConfig={institutionConfig}
                    onAccept={() => void handleAccept(chapter.id, pendingDraft.id)}
                    onReject={() => handleReject(chapter.id, pendingDraft.id)}
                    onDraftUpdated={(version) => handleDraftUpdated(chapter.id, version)}
                  />
                )}
                {!pendingDraft && !streamingContent && (
                  <ChapterDraftUploadForm
                    chapterId={chapter.id}
                    onUploaded={(version) => handleDraftUpdated(chapter.id, version)}
                  />
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function ExportButton() {
  const { document: doc } = useDocument()
  const [isExporting, setIsExporting] = useState(false)
  const [error, setError] = useState(false)

  const handleExport = async () => {
    const projectId = doc.projectId
    if (projectId === null || isExporting) {
      return
    }

    setIsExporting(true)
    setError(false)
    try {
      await exportProject(projectId, doc.institutionId)
    } catch {
      setError(true)
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="export-button">
      <button onClick={() => void handleExport()} disabled={doc.projectId === null || isExporting}>
        {isExporting ? strings.exportButtonPending : strings.exportButton}
      </button>
      {error && <span className="export-error">{strings.exportErrorMessage}</span>}
    </div>
  )
}

function Workspace({ onBackToLanding }: { onBackToLanding: () => void }) {
  const { document: doc } = useDocument()

  return (
    <>
      <div className="workspace-header">
        <button type="button" onClick={onBackToLanding}>
          {strings.myProjectsButton}
        </button>
        <h2 className="workspace-project-title">{doc.title}</h2>
        <ExportButton />
      </div>
      <main className="workspace">
        <ChatPanel />
        <DocumentPanel />
      </main>
    </>
  )
}

type Tab = 'workspace' | 'plagiarism-check'
type WorkspaceView = 'landing' | 'workspace'

/**
 * Clears all client-side session state (JWT + selected project/institution + chat history) and
 * lets `Gate` fall back to rendering `Onboarding` on the next render, since it re-checks
 * `auth.accessToken === null`. There is no server-side session to invalidate — this app has no
 * logout endpoint (or, notably, any auth-gated endpoint at all yet) — so logging out is purely
 * this local reset.
 */
function LogoutButton() {
  const { setAuth } = useAuth()
  const { setDocument } = useDocument()
  const { resetChat } = useChat()

  const handleLogout = () => {
    setAuth(emptyAuthState)
    setDocument(emptyDocumentState)
    resetChat()
  }

  return (
    <button type="button" className="logout-button" onClick={handleLogout}>
      {strings.logoutButton}
    </button>
  )
}

/**
 * Tab navigation shown once a user is past onboarding, per ADR-0008 (no routing
 * library — local useState is enough for two sibling views). "Workspace" is the
 * default tab so existing project/chapter flows are unaffected.
 *
 * Within the "workspace" tab, a `view` sub-state (`'landing' | 'workspace'`) decides
 * whether the project list (`ProjectLanding`) or the chat+preview workspace shows.
 * Landing is the default and is forced whenever there is no active project; picking
 * "My Projects" from the workspace flips back to landing WITHOUT clearing `document`,
 * so an in-progress project's chapters survive a round trip back to the list.
 */
function AuthenticatedApp() {
  const [activeTab, setActiveTab] = useState<Tab>('workspace')
  const { document: doc } = useDocument()
  const [view, setView] = useState<WorkspaceView>(doc.projectId === null ? 'landing' : 'workspace')

  useEffect(() => {
    if (doc.projectId === null) {
      setView('landing')
    }
  }, [doc.projectId])

  return (
    <>
      <header className="app-header">
        <h1>{strings.appTitle}</h1>
        <LogoutButton />
      </header>
      <nav className="tab-bar" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'workspace'}
          className={activeTab === 'workspace' ? 'tab tab--active' : 'tab'}
          onClick={() => setActiveTab('workspace')}
        >
          {strings.tabWorkspaceLabel}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'plagiarism-check'}
          className={activeTab === 'plagiarism-check' ? 'tab tab--active' : 'tab'}
          onClick={() => setActiveTab('plagiarism-check')}
        >
          {strings.tabPlagiarismCheckLabel}
        </button>
      </nav>
      {activeTab === 'workspace' ? (
        view === 'landing' ? (
          <ProjectLanding onProjectActivated={() => setView('workspace')} />
        ) : (
          <Workspace onBackToLanding={() => setView('landing')} />
        )
      ) : (
        <PlagiarismCheckPanel />
      )}
    </>
  )
}

function Gate() {
  const { auth } = useAuth()

  if (auth.accessToken === null) {
    return <Onboarding />
  }

  return <AuthenticatedApp />
}

function App() {
  return (
    <AuthProvider>
      <DocumentProvider>
        <ChatProvider>
          <Gate />
        </ChatProvider>
      </DocumentProvider>
    </AuthProvider>
  )
}

export default App
