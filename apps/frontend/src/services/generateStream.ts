import { strings } from '../strings'
import type { GenerateDraftResult } from '../types/project'

export interface StreamChapterDraftHandlers {
  onToken: (chunk: string) => void
  onDone: (result: GenerateDraftResult) => void
  onError: (message: string) => void
}

/**
 * Opens the SSE stream for chapter-draft generation (ADR-0009) and wires its `token`/`done`/
 * `error` events to `handlers`. Unlike `generateChapterDraft`'s POST, `EventSource` only supports
 * GET with no body, so `instruction` travels as a URL-encoded query param instead.
 *
 * Closes the connection itself once `done` fires, once a custom `error` SSE event fires, or on a
 * connection-level `onerror` (e.g. dropped connection/network failure) — callers don't need to
 * call the returned cleanup function in those cases, only on early unmount.
 */
export function streamChapterDraft(
  projectId: string,
  chapterId: string,
  instruction: string,
  handlers: StreamChapterDraftHandlers,
): () => void {
  const url = new URL(
    `${import.meta.env.VITE_API_BASE_URL}/projects/${projectId}/chapters/${chapterId}/generate/stream`,
  )
  url.searchParams.set('instruction', instruction)

  const source = new EventSource(url.toString())

  source.addEventListener('token', (event) => {
    handlers.onToken((event as MessageEvent<string>).data)
  })

  source.addEventListener('done', (event) => {
    const result = JSON.parse((event as MessageEvent<string>).data) as GenerateDraftResult
    source.close()
    handlers.onDone(result)
  })

  // The backend's custom `error` SSE event and the browser's connection-level failure both
  // dispatch as an event of type "error" on the EventSource (per the SSE spec, the event's type
  // comes straight from the `event:` field, with no reserved exception for "error") — so a single
  // listener handles both, distinguishing them by whether a JSON `data` payload is present.
  source.addEventListener('error', (event) => {
    const messageEvent = event as MessageEvent<string>
    let message: string = strings.chatGenerationErrorMessage
    if (messageEvent.data) {
      try {
        message = (JSON.parse(messageEvent.data) as { detail: string }).detail
      } catch {
        // Malformed payload — fall back to the generic message.
      }
    }
    source.close()
    handlers.onError(message)
  })

  return () => source.close()
}
