import { ACCESS_TOKEN_STORAGE_KEY } from '../context/AuthContext'
import type { RequiredSource } from '../types/project'

/** Same bearer-token pattern as `projectService.ts` — the required-sources endpoints require auth. */
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

  return (await response.json()) as T
}

export function createRequiredSource(
  projectId: string,
  author: string,
  title?: string,
): Promise<RequiredSource> {
  return request<RequiredSource>(`/projects/${projectId}/required-sources`, {
    method: 'POST',
    body: JSON.stringify({ author, title: title ?? null }),
  })
}

export function listRequiredSources(projectId: string): Promise<RequiredSource[]> {
  return request<RequiredSource[]>(`/projects/${projectId}/required-sources`)
}
