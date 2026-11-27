import axios from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { REFRESH_TOKEN_STORAGE_KEY, useAuthStore } from './auth'
import { restoreSession } from '@/api/client'

afterEach(() => vi.restoreAllMocks())

describe('auth store', () => {
  it('keeps the access token in memory only', () => {
    useAuthStore.getState().setTokens({ access_token: 'a1', refresh_token: null })
    expect(useAuthStore.getState()).toMatchObject({ token: 'a1', status: 'signed_in' })
    expect(Object.keys(localStorage)).toEqual([])
    expect(Object.keys(sessionStorage)).toEqual([])
  })

  it('keeps a refresh token it was given (LMS frames) in this tab only', () => {
    useAuthStore.getState().setTokens({ access_token: 'a1', refresh_token: 'r1' })
    expect(sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY)).toBe('r1')
    expect(Object.keys(localStorage)).toEqual([])
    useAuthStore.getState().clear()
    expect(sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY)).toBeNull()
  })
})

describe('restoreSession', () => {
  it('picks the session up from the refresh cookie in its own tab', async () => {
    useAuthStore.setState({ token: null, status: 'restoring' })
    const post = vi.spyOn(axios, 'post').mockResolvedValue({ data: { access_token: 'a2', refresh_token: null } })
    await restoreSession()
    expect(post).toHaveBeenCalledWith('/api/v1/auth/token/refresh', {}, { headers: { 'X-Stacks-Refresh': 'cookie' } })
    expect(useAuthStore.getState()).toMatchObject({ token: 'a2', status: 'signed_in' })
  })
})
