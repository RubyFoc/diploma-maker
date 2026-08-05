import type {
  ChapterDetail,
  ChapterVersion,
  GenerateDraftResult,
  ProjectDetail,
} from '../types/project'

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

export function createProject(title?: string): Promise<ProjectDetail> {
  return request<ProjectDetail>('/projects', {
    method: 'POST',
    body: JSON.stringify(title === undefined ? {} : { title }),
  })
}

export function getProject(projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/projects/${projectId}`)
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
