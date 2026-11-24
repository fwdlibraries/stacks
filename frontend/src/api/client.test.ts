import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import axios, { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios'
import apiClient from './client'
import { useAuthStore } from '@/stores/auth'

const originalAdapter = apiClient.defaults.adapter
const originalLocation = window.location

/** Fake transport: 401 for the expired token, 200 otherwise. Records auth headers. */
function fakeServer(expiredToken: string) {
  const seen: string[] = []
  const adapter: AxiosAdapter = async (config: InternalAxiosRequestConfig) => {
    const auth = String(config.headers.Authorization)
    seen.push(auth)
    if (auth === `Bearer ${expiredToken}`) {
      const response = { status: 401, statusText: 'Unauthorized', data: {}, headers: {}, config }
      throw new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, null, response)
    }
    return { status: 200, statusText: 'OK', data: { ok: true }, headers: {}, config }
  }
  apiClient.defaults.adapter = adapter
  return seen
}

beforeEach(() => {
  // jsdom can't navigate; capture the redirect instead
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { pathname: '/lists', href: '/lists' },
  })
})

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter
  Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
  vi.restoreAllMocks()
  useAuthStore.getState().clear()
})

describe('apiClient 401 handling', () => {
  it('refreshes the access token once and retries the request', async () => {
    useAuthStore.getState().setTokens({ access_token: 'old', refresh_token: 'r1' })
    const seen = fakeServer('old')
    const refresh = vi
      .spyOn(axios, 'post')
      .mockResolvedValue({ data: { access_token: 'new', refresh_token: 'r2' } })

    const resp = await apiClient.get('/lists')

    expect(resp.data).toEqual({ ok: true })
    expect(seen).toEqual(['Bearer old', 'Bearer new'])
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(refresh).toHaveBeenCalledWith('/api/v1/auth/token/refresh', { refresh_token: 'r1' })
    expect(useAuthStore.getState()).toMatchObject({ token: 'new', refreshToken: 'r2' })
  })

  it('shares one refresh between concurrent 401s', async () => {
    useAuthStore.getState().setTokens({ access_token: 'old', refresh_token: 'r1' })
    fakeServer('old')
    const refresh = vi
      .spyOn(axios, 'post')
      .mockResolvedValue({ data: { access_token: 'new', refresh_token: 'r2' } })

    await Promise.all([apiClient.get('/lists'), apiClient.get('/auth/me')])

    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('signs out when the refresh fails', async () => {
    useAuthStore.getState().setTokens({ access_token: 'old', refresh_token: 'r1' })
    fakeServer('old')
    vi.spyOn(axios, 'post').mockRejectedValue(new Error('refresh rejected'))

    await expect(apiClient.get('/lists')).rejects.toBeInstanceOf(AxiosError)

    expect(useAuthStore.getState().token).toBeNull()
    expect(window.location.href).toBe('/login')
  })

  it('leaves failed logins to the login form', async () => {
    const refresh = vi.spyOn(axios, 'post')
    apiClient.defaults.adapter = async (config) => {
      const response = { status: 401, statusText: 'Unauthorized', data: {}, headers: {}, config }
      throw new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, null, response)
    }

    await expect(apiClient.post('/auth/local/login', {})).rejects.toBeInstanceOf(AxiosError)

    expect(refresh).not.toHaveBeenCalled()
    expect(window.location.href).toBe('/lists')
  })
})
