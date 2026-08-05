import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { streamChapterDraft } from './generateStream'
import { strings } from '../strings'

type Listener = (event: { type: string; data?: string }) => void

/**
 * Minimal `EventSource` stand-in — jsdom doesn't implement it. Mirrors the real spec closely
 * enough for this module's needs: `addEventListener` registers per-type listeners, and
 * `dispatch('error')` with no `data` simulates a connection-level failure while
 * `dispatch('error', jsonPayload)` simulates the backend's custom `error` SSE event — both are
 * dispatched as the same event type on a real `EventSource`, which is exactly the ambiguity
 * `generateStream.ts` has to resolve.
 */
class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  closed = false
  private listeners: Record<string, Listener[]> = {}

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners[type] = [...(this.listeners[type] ?? []), listener]
  }

  close() {
    this.closed = true
  }

  dispatch(type: string, data?: string) {
    for (const listener of this.listeners[type] ?? []) {
      listener({ type, data })
    }
  }
}

beforeEach(() => {
  MockEventSource.instances = []
  vi.stubGlobal('EventSource', MockEventSource)
  vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8010')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('streamChapterDraft', () => {
  it('accumulates token events in order via onToken', () => {
    const onToken = vi.fn()
    streamChapterDraft('p1', 'c1', 'write it', { onToken, onDone: vi.fn(), onError: vi.fn() })

    const source = MockEventSource.instances[0]
    source.dispatch('token', 'Hello')
    source.dispatch('token', ', world')

    expect(onToken.mock.calls).toEqual([['Hello'], [', world']])
  })

  it('calls onDone with the parsed payload and closes the connection on a done event', () => {
    const onDone = vi.fn()
    streamChapterDraft('p1', 'c1', 'write it', { onToken: vi.fn(), onDone, onError: vi.fn() })

    const source = MockEventSource.instances[0]
    const result = {
      version: {
        id: 'v1',
        chapter_id: 'c1',
        version_number: 1,
        content: 'Generated text',
        created_at: 'now',
        status: 'draft',
        parent_version_id: null,
      },
      precheck: { plagiarism_score: 0, ai_fingerprint_score: 0, flagged: false, reasons: [] },
    }
    source.dispatch('done', JSON.stringify(result))

    expect(onDone).toHaveBeenCalledWith(result)
    expect(source.closed).toBe(true)
  })

  it('calls onError with the backend detail on a custom error event and closes the connection', () => {
    const onError = vi.fn()
    streamChapterDraft('p1', 'c1', 'write it', { onToken: vi.fn(), onDone: vi.fn(), onError })

    const source = MockEventSource.instances[0]
    source.dispatch('error', JSON.stringify({ detail: 'llm failed' }))

    expect(onError).toHaveBeenCalledWith('llm failed')
    expect(source.closed).toBe(true)
  })

  it('calls onError with a generic message on a connection-level error and closes the connection', () => {
    const onError = vi.fn()
    streamChapterDraft('p1', 'c1', 'write it', { onToken: vi.fn(), onDone: vi.fn(), onError })

    const source = MockEventSource.instances[0]
    source.dispatch('error')

    expect(onError).toHaveBeenCalledWith(strings.chatGenerationErrorMessage)
    expect(source.closed).toBe(true)
  })

  it('encodes the instruction as a URL query param', () => {
    streamChapterDraft('p1', 'c1', 'write it & more', { onToken: vi.fn(), onDone: vi.fn(), onError: vi.fn() })

    const source = MockEventSource.instances[0]
    expect(source.url).toBe(
      'http://localhost:8010/projects/p1/chapters/c1/generate/stream?instruction=write+it+%26+more',
    )
  })

  it('returns a cleanup function that closes the connection', () => {
    const cleanup = streamChapterDraft('p1', 'c1', 'write it', {
      onToken: vi.fn(),
      onDone: vi.fn(),
      onError: vi.fn(),
    })

    const source = MockEventSource.instances[0]
    cleanup()

    expect(source.closed).toBe(true)
  })
})
