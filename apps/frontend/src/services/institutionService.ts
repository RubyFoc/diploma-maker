import type { InstitutionConfig, InstitutionSummary } from '../types/institution'

class RequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}${path}`, init)

  if (!response.ok) {
    const body = await response.text()
    throw new RequestError(`Request to ${path} failed with status ${response.status}: ${body}`, response.status)
  }

  return (await response.json()) as T
}

export function listInstitutions(): Promise<InstitutionSummary[]> {
  return request<InstitutionSummary[]>('/formatting/institution-configs', {
    headers: { 'Content-Type': 'application/json' },
  })
}

export function getInstitutionConfig(institutionId: string): Promise<InstitutionConfig> {
  return request<InstitutionConfig>(`/formatting/institution-configs/${institutionId}`, {
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

/**
 * Best-effort web-search auto-detection of a university's formatting requirements.
 *
 * A 404 from the backend means the search genuinely found nothing confident enough
 * to use — an expected, common outcome, not a failure — so it resolves to `null`
 * rather than throwing. Any other non-2xx status (e.g. 502 search-infrastructure
 * failure) still throws, same as the other institution-config requests.
 */
export async function autoDetectInstitution(universityName: string): Promise<InstitutionSummary | null> {
  try {
    return await request<InstitutionSummary>('/formatting/institution-configs/auto-detect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ institution_name: universityName }),
    })
  } catch (error) {
    if (error instanceof RequestError && error.status === 404) {
      return null
    }
    throw error
  }
}
