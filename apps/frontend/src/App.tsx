import { useState } from 'react'
import './App.css'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ChatProvider, useChat } from './context/ChatContext'
import { DocumentProvider, useDocument } from './context/DocumentContext'
import { useNewProject } from './hooks/useNewProject'
import { strings } from './strings'
import { DiffViewer } from './components/DiffViewer'
import { DocumentPreview } from './components/DocumentPreview'
import { Onboarding } from './components/Onboarding'
import { PlagiarismCheckPanel } from './components/PlagiarismCheckPanel'
import { recordSignal } from './services/feedbackService'
import { acceptDraft, createChapter, getProject } from './services/projectService'
import { streamChapterDraft } from './services/generateStream'
import { toDocumentState } from './utils/mapProject'

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
          pendingDraft: created.pending_draft,
          streamingContent: null,
        }
        setDocument((previous) => ({ ...previous, chapters: [...previous.chapters, chapter] }))
      }

      const chapterId = chapter.id
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
                  ? { ...existing, pendingDraft: draft, streamingContent: null }
                  : existing,
              ),
            }))
            appendMessage({
              id: crypto.randomUUID(),
              role: 'assistant',
              text: precheck.flagged ? strings.chatDraftFlaggedMessage : strings.chatDraftReadyMessage,
            })
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

function DocumentPanel() {
  const { document: doc, setDocument } = useDocument()

  const handleAccept = async (chapterId: string, draftId: string) => {
    await acceptDraft(draftId)
    if (doc.institutionId !== null) {
      void recordSignal(doc.institutionId, chapterId, draftId, 'approve').catch(() => {})
    }
    if (doc.projectId !== null) {
      const project = await getProject(doc.projectId)
      setDocument((previous) => toDocumentState(project, previous.institutionId))
      return
    }
    setDocument((previous) => ({
      ...previous,
      chapters: previous.chapters.map((chapter) =>
        chapter.id === chapterId ? { ...chapter, pendingDraft: null } : chapter,
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
        chapter.id === chapterId ? { ...chapter, pendingDraft: null } : chapter,
      ),
    }))
  }

  return (
    <section className="panel document-panel" aria-label={strings.documentPanelTitle}>
      <h2>{strings.documentPanelTitle}</h2>
      {doc.chapters.length === 0 ? (
        <p className="document-empty">{strings.documentEmpty}</p>
      ) : (
        <ul className="chapter-list">
          {doc.chapters.map((chapter) => {
            const { pendingDraft, streamingContent } = chapter
            return (
              <li key={chapter.id} className="chapter-item">
                <h3>{chapter.title}</h3>
                <DocumentPreview content={chapter.content} />
                {/* Live SSE preview (ADR-0009): shown while tokens are still arriving, before
                    `pendingDraft`/`DiffViewer` take over once `done` fires. Reuses
                    `DocumentPreview` rather than a new component since it already renders
                    arbitrary chapter text and re-renders live as `streamingContent` grows. */}
                {streamingContent !== null && !pendingDraft && (
                  <div className="chapter-streaming" aria-label={strings.chapterStreamingLabel}>
                    <DocumentPreview content={streamingContent} />
                  </div>
                )}
                {pendingDraft && (
                  <DiffViewer
                    before={chapter.content}
                    after={pendingDraft.content}
                    onAccept={() => void handleAccept(chapter.id, pendingDraft.id)}
                    onReject={() => handleReject(chapter.id, pendingDraft.id)}
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

function NewProjectButton() {
  const startNewProject = useNewProject()

  return <button onClick={() => void startNewProject()}>{strings.newProjectButton}</button>
}

function Workspace() {
  return (
    <>
      <div className="workspace-header">
        <NewProjectButton />
      </div>
      <main className="workspace">
        <ChatPanel />
        <DocumentPanel />
      </main>
    </>
  )
}

type Tab = 'workspace' | 'plagiarism-check'

/**
 * Tab navigation shown once a user is past onboarding, per ADR-0008 (no routing
 * library — local useState is enough for two sibling views). "Workspace" is the
 * default tab so existing project/chapter flows are unaffected.
 */
function AuthenticatedApp() {
  const [activeTab, setActiveTab] = useState<Tab>('workspace')

  return (
    <>
      <header className="app-header">
        <h1>{strings.appTitle}</h1>
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
      {activeTab === 'workspace' ? <Workspace /> : <PlagiarismCheckPanel />}
    </>
  )
}

function Gate() {
  const { auth } = useAuth()
  const { document: doc } = useDocument()

  if (auth.accessToken === null || doc.institutionId === null) {
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
