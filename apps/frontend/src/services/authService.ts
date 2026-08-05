import type { TokenResponse } from '../types/auth'

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

export function register(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function login(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}
