import './App.css'
import { ChatProvider, useChat } from './context/ChatContext'
import { DocumentProvider, useDocument } from './context/DocumentContext'
import { useNewProject } from './hooks/useNewProject'
import { strings } from './strings'

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

function DocumentPanel() {
  const { document: doc } = useDocument()

  return (
    <section className="document-panel" aria-label={strings.documentPanelTitle}>
      <h2>{strings.documentPanelTitle}</h2>
      {doc.chapters.length === 0 ? (
        <p>{strings.documentEmpty}</p>
      ) : (
        <ul>
          {doc.chapters.map((chapter) => (
            <li key={chapter.id}>{chapter.title}</li>
          ))}
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
