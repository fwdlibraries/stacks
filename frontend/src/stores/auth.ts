import { create } from 'zustand'

/** localStorage keys; TOKEN_STORAGE_KEY is shared with lib/websocket.ts */
export const TOKEN_STORAGE_KEY = 'stacks_token'
export const REFRESH_TOKEN_STORAGE_KEY = 'stacks_refresh_token'

export interface AuthTokens {
  access_token: string
  refresh_token: string
}

interface AuthState {
  token: string | null
  refreshToken: string | null
  setTokens: (tokens: AuthTokens) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(TOKEN_STORAGE_KEY),
  refreshToken: localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY),
  setTokens: ({ access_token, refresh_token }) => {
    localStorage.setItem(TOKEN_STORAGE_KEY, access_token)
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, refresh_token)
    set({ token: access_token, refreshToken: refresh_token })
  },
  clear: () => {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY)
    set({ token: null, refreshToken: null })
  },
}))
