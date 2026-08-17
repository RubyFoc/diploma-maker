import { ACCESS_TOKEN_STORAGE_KEY } from '../context/AuthContext'
import { notifyAuthExpired } from './authEvents'
import type { OperationsListResponse, UndoRedoResponse } from '../types/history'

/** Wraps `history.router` (ADR-0012, TASK-E16-2/3/4): undo/redo over a chapter's edit op-log,
 * and listing its recorded operations for client-side page-range resolution. Same bearer-token
 * pattern as `lockService.ts`/`projectService.ts` — these endpoints require auth. */
function authHeaders(): Record<string, string> {
  const token = localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Mirrors `projectService.ts`'s `RequestError` — exposes the HTTP status so callers can
// distinguish a 409 (no pending draft / nothing to undo-redo / a vanished anchor block) from
// other failures, per TASK-E16-5's requirement for a distinct conflict message.
export class RequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init?.headers },
  })

  if (!response.ok) {
    if (response.status === 401) {
      notifyAuthExpired()
    }
    const body = await response.text()
    throw new RequestError(`Request to ${path} failed with status ${response.status}: ${body}`, response.status)
  }

  return (await response.json()) as T
}

export function listOperations(chapterId: string): Promise<OperationsListResponse> {
  return request<OperationsListResponse>(`/chapters/${chapterId}/operations`)
}

export function undoChapter(chapterId: string, count = 1): Promise<UndoRedoResponse> {
  return request<UndoRedoResponse>(`/chapters/${chapterId}/undo`, {
    method: 'POST',
    body: JSON.stringify({ count }),
  })
}

export function redoChapter(chapterId: string, count = 1): Promise<UndoRedoResponse> {
  return request<UndoRedoResponse>(`/chapters/${chapterId}/redo`, {
    method: 'POST',
    body: JSON.stringify({ count }),
  })
}
