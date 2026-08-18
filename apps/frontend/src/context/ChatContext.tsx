import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
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

const CHAT_STORAGE_KEY_PREFIX = 'diploma-maker.chat.'

function storageKey(projectId: string): string {
  return `${CHAT_STORAGE_KEY_PREFIX}${projectId}`
}

/** Reads a project's persisted chat history back out of `localStorage`. Swallows any failure
 * (corrupted JSON from a future/incompatible app version, storage disabled, etc.) to an empty
 * history rather than breaking the chat panel over old/bad data. */
function readStoredMessages(projectId: string): ChatMessage[] {
  try {
    const raw = localStorage.getItem(storageKey(projectId))
    return raw ? (JSON.parse(raw) as ChatMessage[]) : []
  } catch {
    return []
  }
}

interface ChatContextValue {
  chat: ChatState
  /** Appends `message` to the active project's chat and persists the updated history to
   * `localStorage` (user request: chat used to be purely in-memory, so it vanished on reload or
   * when switching away from a project and back) — a no-op persistence-wise if no project is
   * active yet (`loadChatForProject` hasn't been called), though the message still shows for
   * this session. */
  appendMessage: (message: ChatMessage) => void
  /** Clears the visible chat back to empty without touching any project's persisted history —
   * for leaving a project's context entirely (e.g. logout), not for destroying data. */
  clearChat: () => void
  /** Switches to `projectId`'s own persisted chat history (or a blank one for a project with
   * none yet), and remembers `projectId` as the one `appendMessage` persists new messages
   * under. Pass `null` to leave no project active (same effect as `clearChat`). */
  loadChatForProject: (projectId: string | null) => void
  /** Permanently deletes `projectId`'s persisted chat history — for when the project itself is
   * deleted (`ProjectLanding`), not for merely navigating away from it. Does not affect the
   * currently *visible* chat unless `projectId` is also the active project (callers that delete
   * the active project should also call `clearChat()`). */
  deleteChatForProject: (projectId: string) => void
}

const ChatContext = createContext<ChatContextValue | undefined>(undefined)

export function ChatProvider({ children }: { children: ReactNode }) {
  const [chat, setChat] = useState<ChatState>(emptyChatState)
  // Which project `appendMessage` should persist new messages under — a ref, not state, since
  // updating it must never itself trigger a render (it only matters the next time a message is
  // appended or a project is loaded).
  const activeProjectIdRef = useRef<string | null>(null)

  const appendMessage = useCallback((message: ChatMessage) => {
    setChat((previous) => {
      const messages = [...previous.messages, message]
      const projectId = activeProjectIdRef.current
      if (projectId !== null) {
        try {
          localStorage.setItem(storageKey(projectId), JSON.stringify(messages))
        } catch {
          // Storage full/unavailable (private browsing, quota) — the chat still works for this
          // session, it just won't survive a reload. Not worth surfacing as a user-facing error
          // for what's a nice-to-have persistence feature, not core functionality.
        }
      }
      return { messages }
    })
  }, [])

  const clearChat = useCallback(() => {
    activeProjectIdRef.current = null
    setChat(emptyChatState)
  }, [])

  const loadChatForProject = useCallback((projectId: string | null) => {
    activeProjectIdRef.current = projectId
    setChat({ messages: projectId !== null ? readStoredMessages(projectId) : [] })
  }, [])

  const deleteChatForProject = useCallback((projectId: string) => {
    localStorage.removeItem(storageKey(projectId))
  }, [])

  const value = useMemo(
    () => ({ chat, appendMessage, clearChat, loadChatForProject, deleteChatForProject }),
    [chat, appendMessage, clearChat, loadChatForProject, deleteChatForProject],
  )

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

export function useChat(): ChatContextValue {
  const context = useContext(ChatContext)
  if (!context) {
    throw new Error('useChat must be used within a ChatProvider')
  }
  return context
}
