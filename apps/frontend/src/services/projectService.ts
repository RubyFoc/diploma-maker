import { ACCESS_TOKEN_STORAGE_KEY } from '../context/AuthContext'
import type {
  ChapterDetail,
  ChapterVersion,
  GenerateDraftResult,
  ProjectDetail,
  ProjectSummary,
} from '../types/project'

/**
 * All `/projects*` endpoints require a bearer token (TASK-E11-1/2/3). This module is a plain
 * (non-React) service, so it reads the token straight out of the same localStorage key
 * `AuthContext` persists it under, rather than requiring every call site to thread it through.
 */
function authHeaders(): Record<string, string> {
  const token = localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Exposes the HTTP status alongside the message (mirrors `institutionService.ts`'s
// `RequestError`) so callers can branch on specific statuses (e.g. TASK-E15-3's 409
// fully-locked-chapter case) instead of re-parsing the error message string.
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
    const body = await response.text()
    throw new RequestError(`Request to ${path} failed with status ${response.status}: ${body}`, response.status)
  }

  // DELETE responses (e.g. deleteProject) return 204 No Content with no body to parse.
  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export function createProject(title?: string): Promise<ProjectDetail> {
  return request<ProjectDetail>('/projects', {
    method: 'POST',
    body: JSON.stringify(title === undefined ? {} : { title }),
  })
}

export function listProjects(): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>('/projects')
}

export function getProject(projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/projects/${projectId}`)
}

export function deleteProject(projectId: string): Promise<void> {
  return request<void>(`/projects/${projectId}`, { method: 'DELETE' })
}

export function createChapter(projectId: string, title: string): Promise<ChapterDetail> {
  return request<ChapterDetail>(`/projects/${projectId}/chapters`, {
    method: 'POST',
    body: JSON.stringify({ title }),
  })
}

export function createSubchapter(
  projectId: string,
  chapterId: string,
  title: string,
): Promise<ChapterDetail> {
  return request<ChapterDetail>(`/projects/${projectId}/chapters/${chapterId}/subchapters`, {
    method: 'POST',
    body: JSON.stringify({ title }),
  })
}

export function listSubchapters(projectId: string, chapterId: string): Promise<ChapterDetail[]> {
  return request<ChapterDetail[]>(`/projects/${projectId}/chapters/${chapterId}/subchapters`)
}

/**
 * `targetBlockId`, when provided, switches the backend to "insert at anchor" mode
 * (TASK-E15-1/2/3, ADR-0011) instead of regenerating the whole chapter. Omitted (or `null`)
 * keeps the request body identical to the pre-E15 shape, for backward compatibility.
 */
export function generateChapterDraft(
  projectId: string,
  chapterId: string,
  instruction: string,
  targetBlockId?: string | null,
): Promise<GenerateDraftResult> {
  const body: { instruction: string; target_block_id?: string } = { instruction }
  if (targetBlockId) {
    body.target_block_id = targetBlockId
  }
  return request<GenerateDraftResult>(`/projects/${projectId}/chapters/${chapterId}/generate`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function acceptDraft(versionId: string): Promise<ChapterVersion> {
  return request<ChapterVersion>(`/versions/${versionId}/accept`, { method: 'POST' })
}
