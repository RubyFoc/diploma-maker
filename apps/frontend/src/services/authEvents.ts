export const AUTH_EXPIRED_EVENT = 'diploma-maker:auth-expired'

/**
 * Called by any authenticated service's `request()` helper when a call comes back 401 — the
 * stored access token is stale/expired but nothing else notices, so every subsequent
 * authenticated call (project creation, listing, etc.) would otherwise keep failing silently
 * forever with no way back to the login screen. `AuthContext` listens for this and clears the
 * token, which drops the app back to the login gate so the user can sign in again.
 */
export function notifyAuthExpired(): void {
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
}
