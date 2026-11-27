import { create } from 'zustand'

/**
 * Where sign-in tokens live (see backend/app/routers/auth.py):
 * - The access token is only ever in memory, so it's gone when the page closes.
 * - In its own tab, Stacks gets the refresh token as an HttpOnly cookie that scripts
 *   can't read. A page load restores the session from it (restoreSession in api/client).
 * - Inside an LMS frame, browsers often block cookies, so the refresh token comes in
 *   the response and is kept in sessionStorage: this tab only, gone when it closes.
 */
export const REFRESH_TOKEN_STORAGE_KEY = 'stacks_refresh_token'

/** True when Stacks is shown inside another page (an LMS). */
export function inFrame(): boolean {
  try {
    return window.self !== window.top
  } catch {
    return true // a cross-origin parent: certainly framed
  }
}

// Earlier versions kept both tokens in localStorage
for (const key of ['stacks_token', 'stacks_refresh_token']) localStorage.removeItem(key)

export interface AuthTokens {
  access_token: string
  /** null when the server set it as an HttpOnly cookie instead */
  refresh_token: string | null
}

export type AuthStatus = 'restoring' | 'signed_in' | 'signed_out'

interface AuthState {
  token: string | null
  /** 'restoring' while a page load tries to pick the session up again */
  status: AuthStatus
  setTokens: (tokens: AuthTokens) => void
  setStatus: (status: AuthStatus) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  status: 'restoring',
  setTokens: ({ access_token, refresh_token }) => {
    if (refresh_token) sessionStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, refresh_token)
    set({ token: access_token, status: 'signed_in' })
  },
  setStatus: (status) => set({ status }),
  clear: () => {
    sessionStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY)
    set({ token: null, status: 'signed_out' })
  },
}))
