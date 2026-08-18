import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { ChatProvider, useChat } from './ChatContext'

function ChatTestHarness() {
  const { chat, appendMessage, clearChat, loadChatForProject, deleteChatForProject } = useChat()

  return (
    <div>
      <ul>
        {chat.messages.map((message) => (
          <li key={message.id}>{message.text}</li>
        ))}
      </ul>
      <button onClick={() => appendMessage({ id: '1', role: 'user', text: 'hello' })}>
        Append
      </button>
      <button onClick={clearChat}>Clear</button>
      <button onClick={() => loadChatForProject('p1')}>Load p1</button>
      <button onClick={() => loadChatForProject('p2')}>Load p2</button>
      <button onClick={() => deleteChatForProject('p1')}>Delete p1</button>
    </div>
  )
}

describe('ChatContext', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('appends a message to the message list', () => {
    render(
      <ChatProvider>
        <ChatTestHarness />
      </ChatProvider>,
    )

    fireEvent.click(screen.getByText('Append'))
    expect(screen.getByText('hello')).toBeInTheDocument()
  })

  it('clears the message list to empty without touching any persisted project history', () => {
    render(
      <ChatProvider>
        <ChatTestHarness />
      </ChatProvider>,
    )

    fireEvent.click(screen.getByText('Load p1'))
    fireEvent.click(screen.getByText('Append'))
    fireEvent.click(screen.getByText('Clear'))
    expect(screen.queryByText('hello')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('Load p1'))
    expect(screen.getByText('hello')).toBeInTheDocument()
  })

  it('persists messages per project and restores them on loadChatForProject', () => {
    render(
      <ChatProvider>
        <ChatTestHarness />
      </ChatProvider>,
    )

    fireEvent.click(screen.getByText('Load p1'))
    fireEvent.click(screen.getByText('Append'))
    expect(screen.getByText('hello')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Load p2'))
    expect(screen.queryByText('hello')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('Load p1'))
    expect(screen.getByText('hello')).toBeInTheDocument()
  })

  it('restores a project\'s persisted history in a freshly mounted provider (survives a reload)', () => {
    const { unmount } = render(
      <ChatProvider>
        <ChatTestHarness />
      </ChatProvider>,
    )
    fireEvent.click(screen.getByText('Load p1'))
    fireEvent.click(screen.getByText('Append'))
    unmount()

    render(
      <ChatProvider>
        <ChatTestHarness />
      </ChatProvider>,
    )
    fireEvent.click(screen.getByText('Load p1'))
    expect(screen.getByText('hello')).toBeInTheDocument()
  })

  it('deleteChatForProject removes a project\'s persisted history permanently', () => {
    render(
      <ChatProvider>
        <ChatTestHarness />
      </ChatProvider>,
    )
    fireEvent.click(screen.getByText('Load p1'))
    fireEvent.click(screen.getByText('Append'))
    fireEvent.click(screen.getByText('Delete p1'))

    fireEvent.click(screen.getByText('Load p2'))
    fireEvent.click(screen.getByText('Load p1'))
    expect(screen.queryByText('hello')).not.toBeInTheDocument()
  })
})
