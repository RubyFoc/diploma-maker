import { ACCESS_TOKEN_STORAGE_KEY } from '../context/AuthContext'
import { notifyAuthExpired } from './authEvents'
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
    if (response.status === 401) {
      notifyAuthExpired()
    }
    const body = await response.text()
    throw new RequestError(`Request to ${path} failed with status ${response.status}: ${body}`, response.status)
  }

  // DELETE responses (e.g. deleteProject) return 204 No Content with no body to parse.
  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

/** Like `request`, but for `multipart/form-data` uploads: omits the JSON `Content-Type` so the
 * browser can set the multipart boundary itself (same reasoning as `institutionService.ts`'s
 * `uploadInstitutionSample`). */
async function requestMultipart<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}${path}`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
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

export function createProject(title?: string, institutionId?: string | null): Promise<ProjectDetail> {
  const body: { title?: string; institution_id?: string } = {}
  if (title !== undefined) {
    body.title = title
  }
  if (institutionId) {
    body.institution_id = institutionId
  }
  return request<ProjectDetail>('/projects', {
    method: 'POST',
    body: JSON.stringify(body),
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

/**
 * Persists a draft rejection on the backend (user report: rejecting used to only clear the
 * frontend's own in-memory state, so the very next full project refetch — accepting a draft in a
 * different chapter, switching projects, reopening the project — would resurrect the "rejected"
 * draft as if it had never been dismissed, since the server never learned about it).
 */
export function rejectDraft(versionId: string): Promise<ChapterVersion> {
  return request<ChapterVersion>(`/versions/${versionId}/reject`, { method: 'POST' })
}

/**
 * Parses an uploaded `.docx` table of contents and creates one chapter per entry, in order
 * (TASK-E10-2/E10-3). Returns the updated `ProjectDetail` with the new chapters.
 */
export function uploadToc(projectId: string, file: File): Promise<ProjectDetail> {
  const formData = new FormData()
  formData.append('file', file)
  return requestMultipart<ProjectDetail>(`/projects/${projectId}/toc/upload`, formData)
}

/**
 * Ingests a whole already-written `.docx` document as multiple chapters in one upload (user
 * request): splits it by `Heading 1` paragraph into `(title, content)` sections, creates one
 * chapter per section, and — for sections with body text — a pending draft version to review,
 * instead of requiring `uploadToc` (titles only) plus a separate `uploadChapterDraft` per
 * chapter.
 */
export function uploadDocument(projectId: string, file: File): Promise<ProjectDetail> {
  const formData = new FormData()
  formData.append('file', file)
  return requestMultipart<ProjectDetail>(`/projects/${projectId}/document/upload`, formData)
}

/**
 * Ingests an already-written `.docx`/`.pdf` draft as a new pending draft version for
 * `chapterId` (TASK-E13-3), so the user's own writing goes through the same accept/reject
 * diff flow as an AI-generated draft.
 */
export function uploadChapterDraft(chapterId: string, file: File): Promise<ChapterVersion> {
  const formData = new FormData()
  formData.append('file', file)
  return requestMultipart<ChapterVersion>(`/chapters/${chapterId}/draft/upload`, formData)
}
