import { useState } from 'react'
import './App.css'
import { ChatProvider, useChat } from './context/ChatContext'
import { DocumentProvider, useDocument } from './context/DocumentContext'
import { useNewProject } from './hooks/useNewProject'
import { strings } from './strings'
import { DiffViewer } from './components/DiffViewer'

function ChatPanel() {
  const { chat } = useChat()

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
    </section>
  )
}

// Placeholder pending-draft simulation for TASK-E08-2. There is no backend
// draft-fetching wired up yet (E08-1's endpoint doesn't exist), so this local
// state stands in for "a chapter has a pending LLM-proposed draft" per
// ADR-0004. A later integration task should replace `pendingDraft` with a
// real fetch of the draft version for the selected chapter and replace
// accept/reject handlers with real API calls instead of clearing local state.
function DocumentPanel() {
  const { document: doc } = useDocument()
  const [pendingDraft, setPendingDraft] = useState<{ chapterId: string; content: string } | null>(
    null,
  )

  const draftChapter = doc.chapters.find((chapter) => chapter.id === pendingDraft?.chapterId)

  return (
    <section className="document-panel" aria-label={strings.documentPanelTitle}>
      <h2>{strings.documentPanelTitle}</h2>
      {doc.chapters.length === 0 ? (
        <p>{strings.documentEmpty}</p>
      ) : (
        <ul>
          {doc.chapters.map((chapter) => (
            <li key={chapter.id}>
              {chapter.title}
              {pendingDraft === null && (
                <button
                  type="button"
                  onClick={() =>
                    setPendingDraft({ chapterId: chapter.id, content: `${chapter.content}\n(draft edit)` })
                  }
                >
                  {strings.simulatePendingDraftButton}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {pendingDraft && draftChapter && (
        <DiffViewer
          before={draftChapter.content}
          after={pendingDraft.content}
          onAccept={() => setPendingDraft(null)}
          onReject={() => setPendingDraft(null)}
        />
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
