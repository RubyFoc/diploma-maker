// Backend API contract types for the auth endpoints (TASK-E10-1).

export interface TokenResponse {
  access_token: string
  token_type: string
}
