import type { PlagiarismCheckResult } from '../types/project'

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
 * Runs a standalone plagiarism/AI-fingerprint check against arbitrary text,
 * independent of any project or chapter (see plagiarismService's caller,
 * PlagiarismCheckPanel, wired outside the DocumentContext/ChatContext tree).
 */
export function checkPlagiarism(
  text: string,
  sourceExcerpts?: string[],
): Promise<PlagiarismCheckResult> {
  return request<PlagiarismCheckResult>('/plagiarism/check', {
    method: 'POST',
    body: JSON.stringify(
      sourceExcerpts === undefined ? { text } : { text, source_excerpts: sourceExcerpts },
    ),
  })
}
