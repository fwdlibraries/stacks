import { describe, expect, it } from 'vitest'
import { REFRESH_TOKEN_STORAGE_KEY, TOKEN_STORAGE_KEY, useAuthStore } from './auth'

describe('auth store', () => {
  it('picks up tokens another tab rotated', () => {
    useAuthStore.getState().setTokens({ access_token: 'a1', refresh_token: 'r1' })
    // Another tab refreshed: localStorage changed underneath this one
    localStorage.setItem(TOKEN_STORAGE_KEY, 'a2')
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, 'r2')
    window.dispatchEvent(new StorageEvent('storage', { key: REFRESH_TOKEN_STORAGE_KEY }))
    expect(useAuthStore.getState()).toMatchObject({ token: 'a2', refreshToken: 'r2' })
  })

  it('signs this tab out when another tab signs out', () => {
    useAuthStore.getState().setTokens({ access_token: 'a1', refresh_token: 'r1' })
    localStorage.clear()
    window.dispatchEvent(new StorageEvent('storage', { key: null }))
    expect(useAuthStore.getState()).toMatchObject({ token: null, refreshToken: null })
  })
})
