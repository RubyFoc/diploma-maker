import { useState } from 'react'
import './App.css'
import { ChatProvider, useChat } from './context/ChatContext'
import { DocumentProvider, useDocument } from './context/DocumentContext'
import { useNewProject } from './hooks/useNewProject'
import { strings } from './strings'
import { DiffViewer } from './components/DiffViewer'
import { acceptDraft, createChapter, generateChapterDraft, getProject } from './services/projectService'
import { toDocumentState } from './utils/mapProject'

function ChatPanel() {
  const { chat, appendMessage } = useChat()
  const { document: doc, setDocument } = useDocument()
  const [inputValue, setInputValue] = useState('')
  const [isSending, setIsSending] = useState(false)

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
        }
        setDocument((previous) => ({ ...previous, chapters: [...previous.chapters, chapter] }))
      }

      const draft = await generateChapterDraft(projectId, chapter.id, text)
      setDocument((previous) => ({
        ...previous,
        chapters: previous.chapters.map((existing) =>
          existing.id === chapter.id ? { ...existing, pendingDraft: draft } : existing,
        ),
      }))
      appendMessage({ id: crypto.randomUUID(), role: 'assistant', text: strings.chatDraftReadyMessage })
    } catch {
      appendMessage({ id: crypto.randomUUID(), role: 'assistant', text: strings.chatGenerationErrorMessage })
    } finally {
      setIsSending(false)
    }
  }

  return (
    <section className="chat-panel" aria-label={strings.chatPanelTitle}>
      <h2>{strings.chatPanelTitle}</h2>
      <div className="chat-messages">
        {chat.messages.length === 0 ? (
          <p>{strings.chatEmpty}</p>
        ) : (
          <ul>
            {chat.messages.map((message) => (
              <li key={message.id}>
                <strong>{message.role}:</strong> {message.text}
              </li>
            ))}
          </ul>
        )}
      </div>
      <form
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
    if (doc.projectId !== null) {
      const project = await getProject(doc.projectId)
      setDocument(toDocumentState(project))
      return
    }
    setDocument((previous) => ({
      ...previous,
      chapters: previous.chapters.map((chapter) =>
        chapter.id === chapterId ? { ...chapter, pendingDraft: null } : chapter,
      ),
    }))
  }

  const handleReject = (chapterId: string) => {
    setDocument((previous) => ({
      ...previous,
      chapters: previous.chapters.map((chapter) =>
        chapter.id === chapterId ? { ...chapter, pendingDraft: null } : chapter,
      ),
    }))
  }

  return (
    <section className="document-panel" aria-label={strings.documentPanelTitle}>
      <h2>{strings.documentPanelTitle}</h2>
      {doc.chapters.length === 0 ? (
        <p>{strings.documentEmpty}</p>
      ) : (
        <ul>
          {doc.chapters.map((chapter) => {
            const { pendingDraft } = chapter
            return (
              <li key={chapter.id}>
                <h3>{chapter.title}</h3>
                <p>{chapter.content === '' ? strings.chapterContentEmpty : chapter.content}</p>
                {pendingDraft && (
                  <DiffViewer
                    before={chapter.content}
                    after={pendingDraft.content}
                    onAccept={() => void handleAccept(chapter.id, pendingDraft.id)}
                    onReject={() => handleReject(chapter.id)}
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
      <header className="workspace-header">
        <h1>{strings.appTitle}</h1>
        <NewProjectButton />
      </header>
      <main className="workspace">
        <ChatPanel />
        <DocumentPanel />
      </main>
    </>
  )
}

function App() {
  return (
    <DocumentProvider>
      <ChatProvider>
        <Workspace />
      </ChatProvider>
    </DocumentProvider>
  )
}

export default App
