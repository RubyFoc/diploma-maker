import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: ChatRole
  text: string
}

export interface ChatState {
  messages: ChatMessage[]
}

export const emptyChatState: ChatState = { messages: [] }

interface ChatContextValue {
  chat: ChatState
  appendMessage: (message: ChatMessage) => void
  resetChat: () => void
}

const ChatContext = createContext<ChatContextValue | undefined>(undefined)

export function ChatProvider({ children }: { children: ReactNode }) {
  const [chat, setChat] = useState<ChatState>(emptyChatState)

  const appendMessage = useCallback((message: ChatMessage) => {
    setChat((previous) => ({ messages: [...previous.messages, message] }))
  }, [])

  const resetChat = useCallback(() => {
    setChat(emptyChatState)
  }, [])

  const value = useMemo(() => ({ chat, appendMessage, resetChat }), [chat, appendMessage, resetChat])

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

export function useChat(): ChatContextValue {
  const context = useContext(ChatContext)
  if (!context) {
    throw new Error('useChat must be used within a ChatProvider')
  }
  return context
}
