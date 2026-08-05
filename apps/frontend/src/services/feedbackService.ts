import type { FeedbackSignal, SignalType } from '../types/feedback'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })

  if (!response.ok) {
    const body = await response.text()
    throw new Error(`Request to ${path} failed with status ${response.status}: ${body}`)
  }

  return (await response.json()) as T
}

/**
 * Records an approve/reject/edit signal against a chapter version (TASK-E09-1).
 * Callers should treat this as best-effort/fire-and-forget: a failure here must
 * never block or fail the accept/reject flow the user is waiting on.
 */
export function recordSignal(
  institutionId: string,
  chapterId: string,
  versionId: string,
  signalType: SignalType,
): Promise<FeedbackSignal> {
  return request<FeedbackSignal>('/feedback/signals', {
    method: 'POST',
    body: JSON.stringify({
      institution_id: institutionId,
      chapter_id: chapterId,
      version_id: versionId,
      signal_type: signalType,
    }),
  })
}
