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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init?.headers },
  })

  if (!response.ok) {
    const body = await response.text()
    throw new Error(`Request to ${path} failed with status ${response.status}: ${body}`)
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

export function generateChapterDraft(
  projectId: string,
  chapterId: string,
  instruction: string,
): Promise<GenerateDraftResult> {
  return request<GenerateDraftResult>(`/projects/${projectId}/chapters/${chapterId}/generate`, {
    method: 'POST',
    body: JSON.stringify({ instruction }),
  })
}

export function acceptDraft(versionId: string): Promise<ChapterVersion> {
  return request<ChapterVersion>(`/versions/${versionId}/accept`, { method: 'POST' })
}
