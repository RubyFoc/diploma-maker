import type { InstitutionSummary } from '../types/institution'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}${path}`, init)

  if (!response.ok) {
    const body = await response.text()
    throw new Error(`Request to ${path} failed with status ${response.status}: ${body}`)
  }

  return (await response.json()) as T
}

export function listInstitutions(): Promise<InstitutionSummary[]> {
  return request<InstitutionSummary[]>('/formatting/institution-configs', {
    headers: { 'Content-Type': 'application/json' },
  })
}

export function uploadInstitutionSample(institutionName: string, file: File): Promise<InstitutionSummary> {
  const formData = new FormData()
  formData.append('institution_name', institutionName)
  formData.append('file', file)

  // No Content-Type header here: the browser sets the multipart boundary automatically.
  return request<InstitutionSummary>('/formatting/institution-configs/upload', {
    method: 'POST',
    body: formData,
  })
}
