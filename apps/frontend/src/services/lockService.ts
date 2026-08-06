import { ACCESS_TOKEN_STORAGE_KEY } from '../context/AuthContext'
import type { CharRange, Lock } from '../types/project'

/** Same bearer-token pattern as `projectService.ts` — the `/chapters` lock endpoints require auth (TASK-E13-4). */
function authHeaders(): Record<string, string> {
  const token = localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init?.headers },
  })

  if (!response.ok) {
    const body = await response.text()
    throw new Error(`Request to ${path} failed with status ${response.status}: ${body}`)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export function listLocks(chapterId: string): Promise<Lock[]> {
  return request<Lock[]>(`/chapters/${chapterId}/locks`)
}

export function createLock(
  chapterId: string,
  blockId: string,
  blockContentHash: string,
  charRange?: CharRange,
): Promise<Lock> {
  return request<Lock>(`/chapters/${chapterId}/locks`, {
    method: 'POST',
    body: JSON.stringify({
      block_id: blockId,
      block_content_hash: blockContentHash,
      char_range: charRange ?? null,
    }),
  })
}

export function deleteLock(chapterId: string, lockId: string): Promise<void> {
  return request<void>(`/chapters/${chapterId}/locks/${lockId}`, { method: 'DELETE' })
}
