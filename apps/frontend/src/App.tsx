import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import { AuthProvider, emptyAuthState, useAuth } from './context/AuthContext'
import { ChatProvider, useChat } from './context/ChatContext'
import { DocumentProvider, emptyDocumentState, useDocument } from './context/DocumentContext'
import { useInstitutionConfig } from './hooks/useInstitutionConfig'
import { strings } from './strings'
import { DiffViewer } from './components/DiffViewer'
import { DocumentPreview } from './components/DocumentPreview'
import { Linkify } from './components/Linkify'
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
  listSubchapters,
  uploadChapterDraft,
  uploadDocument,
  uploadToc,
} from './services/projectService'
import { streamChapterDraft } from './services/generateStream'
import {
  createRequiredSource,
  listRequiredSources,
  parseRequiredSourcesBulk,
} from './services/requiredSourcesService'
import { toDocumentState } from './utils/mapProject'
import type { Chapter } from './context/DocumentContext'
import type { InstitutionConfig } from './types/institution'
import type { ChapterDetail, ChapterVersion, RequiredSource } from './types/project'

interface ChapterTarget {
  id: string
  label: string
}

/**
 * Flattens `chapters` (top-level only) plus each one's subchapters into a single pickable list
 * for `ChatPanel`'s target selector, so a chat instruction can be aimed at a subchapter — not
 * stored in `DocumentContext` at all (see `SubchaptersList`) — the same way it can a top-level
 * chapter. Refetches whenever the top-level chapter set changes; does not react to
 * `subchaptersRefreshToken` since a newly-generated draft doesn't add/remove any subchapters,
 * only fills one in.
 */
function useChapterTargets(projectId: string | null, chapters: Chapter[]): ChapterTarget[] {
  const [targets, setTargets] = useState<ChapterTarget[]>([])
  const chapterIdsKey = chapters.map((chapter) => chapter.id).join(',')

  useEffect(() => {
    if (projectId === null || chapters.length === 0) {
      setTargets([])
      return
    }
    let cancelled = false
    Promise.all(
      chapters.map((chapter) => listSubchapters(projectId, chapter.id).catch(() => [] as ChapterDetail[])),
    ).then((subchaptersByChapter) => {
      if (cancelled) {
        return
      }
      const flat: ChapterTarget[] = []
      chapters.forEach((chapter, index) => {
        flat.push({ id: chapter.id, label: chapter.title })
        for (const subchapter of subchaptersByChapter[index]) {
          flat.push({ id: subchapter.id, label: `— ${subchapter.title}` })
        }
      })
      setTargets(flat)
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, chapterIdsKey])

  return targets
}

function ChatPanel() {
  const { chat, appendMessage } = useChat()
  const { document: doc, setDocument } = useDocument()
  const [inputValue, setInputValue] = useState('')
  const [isSending, setIsSending] = useState(false)
  const targets = useChapterTargets(doc.projectId, doc.chapters)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)

  // User report: a long instruction sent to the chat "disappeared" — really it landed below the
  // fold, since the message list never scrolled itself down on a new message (only `overflow-y:
  // auto` from the bounded-height fix, no scroll-to-bottom behavior). Every new message, sent or
  // received, should bring the latest one into view.
  useEffect(() => {
    // jsdom (used by this app's component tests) doesn't implement `scrollIntoView` at all —
    // guard rather than call it unconditionally, since a real browser always has it.
    messagesEndRef.current?.scrollIntoView?.({ block: 'end' })
  }, [chat.messages])

  // Grows the textarea to fit what's typed (up to `max-height` in App.css, which then scrolls
  // internally) instead of the fixed one-line height a plain `rows={1}` would otherwise freeze it
  // at — resetting to 'auto' first lets it shrink back down too, e.g. after sending clears it.
  useEffect(() => {
    const el = inputRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = `${el.scrollHeight}px`
    }
  }, [inputValue])

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

  // The target may be a subchapter (not in `doc.chapters` at all — see `SubchaptersList`), in
  // which case anchor-mode "insert here" selection doesn't apply (subchapters carry no
  // `selectedAnchorBlockId` of their own) and streaming/pending-draft updates below go through
  // `subchaptersRefreshToken` instead of `doc.chapters`.
  const targetTopLevelChapter = doc.chapters.find((chapter) => chapter.id === doc.selectedChatTargetId) ?? null
  const selectedAnchorBlockId = targetTopLevelChapter?.selectedAnchorBlockId ?? null

  const bumpSubchaptersRefreshToken = () => {
    setDocument((previous) => ({ ...previous, subchaptersRefreshToken: previous.subchaptersRefreshToken + 1 }))
  }

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
      let chapterId = doc.selectedChatTargetId
      let isTopLevel = doc.chapters.some((chapter) => chapter.id === chapterId)
      if (chapterId === null) {
        // Bootstrap: no chapter exists/is selected yet — create the first default chapter, same
        // as this app's original single-chapter behavior.
        const created = await createChapter(projectId, strings.defaultChapterTitle)
        const newChapter: Chapter = {
          id: created.id,
          title: created.title,
          content: created.accepted_content ?? '',
          acceptedManifest: created.accepted_manifest,
          pendingDraft: created.pending_draft,
          streamingContent: null,
          selectedAnchorBlockId: null,
          pendingDraftReroute: null,
        }
        setDocument((previous) => ({
          ...previous,
          chapters: [...previous.chapters, newChapter],
          selectedChatTargetId: newChapter.id,
        }))
        chapterId = newChapter.id
        isTopLevel = true
      }

      // "Insert at anchor" mode (TASK-E15-1/3): a block was selected via the "insert here"
      // toggle in DocumentPreview. Clear the selection now — before generation starts, per this
      // task's spec — rather than only on accept/reject, so a stale selection can't silently
      // reapply to an unrelated follow-up instruction. Only ever set for the top-level target.
      const anchorBlockId = isTopLevel ? (doc.chapters.find((c) => c.id === chapterId)?.selectedAnchorBlockId ?? null) : null
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
          if (result.unmet_required_sources.length > 0) {
            appendMessage({
              id: crypto.randomUUID(),
              role: 'assistant',
              text: strings.chatUnmetRequiredSourcesMessage(result.unmet_required_sources),
            })
          }
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
      if (isTopLevel) {
        setChapterStreamingContent(chapterId, '')
      }

      await new Promise<void>((resolve) => {
        const cleanup = streamChapterDraft(projectId, chapterId, text, {
          onToken: (chunk) => {
            streamedText += chunk
            if (isTopLevel) {
              setChapterStreamingContent(chapterId, streamedText)
            }
          },
          onDone: ({ version: draft, precheck, unmet_required_sources: unmetRequiredSources = [] }) => {
            if (isTopLevel) {
              setDocument((previous) => ({
                ...previous,
                chapters: previous.chapters.map((existing) =>
                  existing.id === chapterId
                    ? { ...existing, pendingDraft: draft, pendingDraftReroute: null, streamingContent: null }
                    : existing,
                ),
              }))
            } else {
              // The target was a subchapter: its pending draft already landed on the backend,
              // but subchapters live in `SubchaptersList`'s own fetched state, not here — bump
              // the shared refresh token so it refetches and picks the new draft up.
              bumpSubchaptersRefreshToken()
            }
            appendMessage({
              id: crypto.randomUUID(),
              role: 'assistant',
              text: precheck.flagged ? strings.chatDraftFlaggedMessage : strings.chatDraftReadyMessage,
            })
            if (unmetRequiredSources.length > 0) {
              appendMessage({
                id: crypto.randomUUID(),
                role: 'assistant',
                text: strings.chatUnmetRequiredSourcesMessage(unmetRequiredSources),
              })
            }
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
            if (isTopLevel) {
              setChapterStreamingContent(chapterId, null)
            }
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
      {targets.length > 0 && (
        <label className="chat-target-select">
          {strings.chatTargetLabel}
          <select
            value={doc.selectedChatTargetId ?? ''}
            onChange={(event) =>
              setDocument((previous) => ({ ...previous, selectedChatTargetId: event.target.value || null }))
            }
          >
            {targets.map((target) => (
              <option key={target.id} value={target.id}>
                {target.label}
              </option>
            ))}
          </select>
        </label>
      )}
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
        <div ref={messagesEndRef} />
      </div>
      {selectedAnchorBlockId !== null && targetTopLevelChapter && (
        <div className="chat-anchor-indicator">
          <span>{strings.chatInsertingAtIndicator}</span>
          <button type="button" onClick={() => clearChapterAnchor(targetTopLevelChapter.id)}>
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
        <textarea
          ref={inputRef}
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends (matching the old single-line <input>'s behavior); Shift+Enter inserts
            // a newline, since a <textarea> otherwise can't ever produce one from the keyboard.
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void handleSend()
            }
          }}
          placeholder={strings.chatInputPlaceholder}
          aria-label={strings.chatInputPlaceholder}
          disabled={doc.projectId === null || isSending}
          rows={1}
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

/**
 * Renders one subchapter (title, content/diff, draft upload) inline under its parent chapter in
 * `DocumentPanel` (user request: subchapters created via TOC/whole-document upload, TASK-E12-1/
 * E12-2, had no UI showing them anywhere — `ChapterTree` exists but was never wired into the
 * workspace). Keeps its own local state rather than folding into `DocumentContext.chapters`
 * (which only ever held top-level chapters) — simplest way to make subchapters reviewable
 * without restructuring that top-level-only state shape.
 */
function SubchapterItem({
  subchapter,
  institutionId,
  institutionConfig,
}: {
  subchapter: ChapterDetail
  institutionId: string | null
  institutionConfig: InstitutionConfig | null
}) {
  const [content, setContent] = useState(subchapter.accepted_content ?? '')
  const [acceptedManifest, setAcceptedManifest] = useState(subchapter.accepted_manifest)
  const [pendingDraft, setPendingDraft] = useState<ChapterVersion | null>(subchapter.pending_draft)

  const handleAccept = async () => {
    if (!pendingDraft) {
      return
    }
    const accepted = await acceptDraft(pendingDraft.id)
    if (institutionId !== null) {
      void recordSignal(institutionId, subchapter.id, accepted.id, 'approve').catch(() => {})
    }
    setContent(accepted.content)
    setAcceptedManifest(accepted.manifest)
    setPendingDraft(null)
  }

  const handleReject = () => {
    if (pendingDraft && institutionId !== null) {
      void recordSignal(institutionId, subchapter.id, pendingDraft.id, 'reject').catch(() => {})
    }
    setPendingDraft(null)
  }

  return (
    <li className="subchapter-item">
      <h4>{subchapter.title}</h4>
      <DocumentPreview
        content={content}
        institutionConfig={institutionConfig}
        chapterId={subchapter.id}
        acceptedManifest={acceptedManifest}
      />
      {pendingDraft ? (
        <DiffViewer
          before={content}
          after={pendingDraft.content}
          onAccept={() => void handleAccept()}
          onReject={handleReject}
          institutionConfig={institutionConfig}
          manifest={pendingDraft.manifest}
        />
      ) : (
        <ChapterDraftUploadForm chapterId={subchapter.id} onUploaded={setPendingDraft} />
      )}
    </li>
  )
}

/** Fetches and renders `parentChapterId`'s subchapters (TASK-E12-2), or nothing if it has none. */
function SubchaptersList({
  projectId,
  parentChapterId,
  institutionId,
  institutionConfig,
  refreshToken,
}: {
  projectId: string
  parentChapterId: string
  institutionId: string | null
  institutionConfig: InstitutionConfig | null
  /** Bumped by `ChatPanel` after a chat generation targets a subchapter (see
   * `DocumentContext.subchaptersRefreshToken`'s doc comment), forcing a refetch to pick up the
   * new pending draft — this component's own state is otherwise the only copy of it. */
  refreshToken: number
}) {
  const [subchapters, setSubchapters] = useState<ChapterDetail[]>([])

  useEffect(() => {
    let cancelled = false
    listSubchapters(projectId, parentChapterId)
      .then((result) => {
        if (!cancelled) {
          setSubchapters(result)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSubchapters([])
        }
      })
    return () => {
      cancelled = true
    }
  }, [projectId, parentChapterId, refreshToken])

  if (subchapters.length === 0) {
    return null
  }

  return (
    <ul className="subchapter-list">
      {subchapters.map((subchapter) => (
        <SubchapterItem
          key={subchapter.id}
          subchapter={subchapter}
          institutionId={institutionId}
          institutionConfig={institutionConfig}
        />
      ))}
    </ul>
  )
}

/**
 * Lets the user view and add must-cite authors/works (TASK-E14) for the life of the project,
 * not just once at creation time (user request: `NewProjectSetup`'s required-sources UI only
 * ever ran during new-project setup — there was no way back into it afterward). Reuses the same
 * one-at-a-time and bulk-paste-auto-detect flows, but posts straight to the now-existing
 * project via `createRequiredSource` instead of staging into `DocumentContext.
 * pendingRequiredSources` (that staging area only exists for the pre-creation case, per its own
 * doc comment).
 */
function RequiredSourcesManager({ projectId }: { projectId: string }) {
  const [sources, setSources] = useState<RequiredSource[]>([])
  const [loadError, setLoadError] = useState(false)
  const [author, setAuthor] = useState('')
  const [title, setTitle] = useState('')
  const [addError, setAddError] = useState(false)
  const [bulkText, setBulkText] = useState('')
  const [isBulkDetecting, setIsBulkDetecting] = useState(false)
  const [bulkMessage, setBulkMessage] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listRequiredSources(projectId)
      .then((result) => {
        if (!cancelled) {
          setSources(result)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError(true)
        }
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  const sourceKey = (author: string, title: string | null) => `${author.trim().toLowerCase()}|${(title ?? '').trim().toLowerCase()}`

  const handleAdd = async (event: FormEvent) => {
    event.preventDefault()
    const trimmedAuthor = author.trim()
    if (trimmedAuthor === '') {
      return
    }
    setAddError(false)
    try {
      const created = await createRequiredSource(projectId, trimmedAuthor, title.trim() || undefined)
      setSources((previous) => [...previous, created])
      setAuthor('')
      setTitle('')
    } catch {
      setAddError(true)
    }
  }

  const handleBulkDetect = async (event: FormEvent) => {
    event.preventDefault()
    const text = bulkText.trim()
    if (text === '' || isBulkDetecting) {
      return
    }
    setIsBulkDetecting(true)
    setBulkMessage(null)
    try {
      const detected = await parseRequiredSourcesBulk(text)
      if (detected.length === 0) {
        setBulkMessage(strings.newProjectSetupRequiredSourceBulkEmptyMessage)
        return
      }
      const existingKeys = new Set(sources.map((source) => sourceKey(source.author, source.title)))
      const newOnes = detected.filter((source) => !existingKeys.has(sourceKey(source.author, source.title ?? null)))
      const created = await Promise.all(newOnes.map((source) => createRequiredSource(projectId, source.author, source.title)))
      setSources((previous) => [...previous, ...created])
      setBulkText('')
    } catch {
      setBulkMessage(strings.newProjectSetupRequiredSourceBulkError)
    } finally {
      setIsBulkDetecting(false)
    }
  }

  return (
    <div className="required-sources-manager">
      <h3>{strings.requiredSourcesManagerTitle}</h3>
      <p className="document-panel-hint">{strings.requiredSourcesManagerSubtitle}</p>
      {loadError && <p className="document-panel-error">{strings.requiredSourcesManagerLoadError}</p>}
      {sources.length > 0 && (
        <ul className="onboarding-required-sources-list">
          {sources.map((source) => (
            <li key={source.id}>
              <span>
                <Linkify text={source.title ? `${source.author} — ${source.title}` : source.author} />
              </span>
            </li>
          ))}
        </ul>
      )}
      {sources.length === 0 && !loadError && <p className="document-panel-hint">{strings.requiredSourcesManagerEmpty}</p>}
      <form className="onboarding-form" onSubmit={(event) => void handleAdd(event)}>
        <label>
          {strings.newProjectSetupRequiredSourceAuthorLabel}
          <input type="text" value={author} onChange={(event) => setAuthor(event.target.value)} />
        </label>
        <label>
          {strings.newProjectSetupRequiredSourceTitleLabel}
          <input type="text" value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <button type="submit">{strings.newProjectSetupRequiredSourceAddButton}</button>
        {addError && <p className="document-panel-error">{strings.requiredSourcesManagerAddError}</p>}
      </form>
      <form className="onboarding-form" onSubmit={(event) => void handleBulkDetect(event)}>
        <label>
          {strings.newProjectSetupRequiredSourceBulkLabel}
          <textarea
            rows={4}
            placeholder={strings.newProjectSetupRequiredSourceBulkPlaceholder}
            value={bulkText}
            onChange={(event) => setBulkText(event.target.value)}
          />
        </label>
        {bulkMessage !== null && <p className="document-panel-error">{bulkMessage}</p>}
        <button type="submit" disabled={isBulkDetecting || bulkText.trim() === ''}>
          {isBulkDetecting
            ? strings.newProjectSetupRequiredSourceBulkButtonPending
            : strings.newProjectSetupRequiredSourceBulkButton}
        </button>
      </form>
    </div>
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
      {doc.projectId && <RequiredSourcesManager projectId={doc.projectId} />}
      <DocumentUploadForm />
      <TocUploadForm />
      {doc.chapters.length === 0 ? (
        <p className="document-empty">{strings.documentEmpty}</p>
      ) : (
        <ul className="chapter-list">
          {doc.chapters.map((chapter) => {
            const { pendingDraft, streamingContent } = chapter
            // ChatPanel.handleSend generates into whichever chapter `doc.selectedChatTargetId`
            // names (user-picked via its target selector), so the "insert here" toggle must
            // only be offered there too — otherwise a selection on any other chapter would be
            // inert. Subchapters never get this toggle at all (see `SubchapterItem`).
            const isChatTargetChapter = chapter.id === doc.selectedChatTargetId
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
                {doc.projectId && (
                  <SubchaptersList
                    projectId={doc.projectId}
                    parentChapterId={chapter.id}
                    institutionId={doc.institutionId}
                    institutionConfig={institutionConfig}
                    refreshToken={doc.subchaptersRefreshToken}
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
  const { clearChat } = useChat()

  const handleLogout = () => {
    setAuth(emptyAuthState)
    setDocument(emptyDocumentState)
    clearChat()
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
