import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ChatProvider, useChat } from './ChatContext'

function ChatTestHarness() {
  const { chat, appendMessage, resetChat } = useChat()

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
      <button onClick={resetChat}>Reset</button>
    </div>
  )
}

describe('ChatContext', () => {
  it('appends a message to the message list', () => {
    render(
      <ChatProvider>
        <ChatTestHarness />
      </ChatProvider>,
    )

    fireEvent.click(screen.getByText('Append'))
    expect(screen.getByText('hello')).toBeInTheDocument()
  })

  it('resets the message list to empty', () => {
    render(
      <ChatProvider>
        <ChatTestHarness />
      </ChatProvider>,
    )

    fireEvent.click(screen.getByText('Append'))
    fireEvent.click(screen.getByText('Reset'))
    expect(screen.queryByText('hello')).not.toBeInTheDocument()
  })
})
