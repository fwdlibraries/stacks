import { create } from 'zustand'

/** localStorage key shared with api/client.ts and lib/websocket.ts */
export const TOKEN_STORAGE_KEY = 'stacks_token'

interface AuthState {
  token: string | null
  setToken: (token: string) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(TOKEN_STORAGE_KEY),
  setToken: (token) => {
    localStorage.setItem(TOKEN_STORAGE_KEY, token)
    set({ token })
  },
  clear: () => {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    set({ token: null })
  },
}))
