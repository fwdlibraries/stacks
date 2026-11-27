import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { REFRESH_TOKEN_STORAGE_KEY, inFrame, useAuthStore, type AuthTokens } from '@/stores/auth'

export const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

/** In its own tab, ask for the refresh token as an HttpOnly cookie (stores/auth.ts). */
function refreshHeaders(): Record<string, string> {
  return inFrame() ? {} : { 'X-Stacks-Refresh': 'cookie' }
}

// Attach auth token to every request
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  for (const [name, value] of Object.entries(refreshHeaders())) config.headers.set(name, value)
  return config
})

/**
 * One in-flight refresh shared by every request that hits a 401 at the same time,
 * so a page firing several queries doesn't trigger several refreshes.
 */
let refreshInFlight: Promise<string | null> | null = null

function refreshAccessToken(): Promise<string | null> {
  // In a frame the refresh token is in this tab's sessionStorage; otherwise the browser
  // sends the HttpOnly cookie
  const refreshToken = inFrame() ? sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY) : null
  if (inFrame() && !refreshToken) return Promise.resolve(null)

  refreshInFlight ??= axios
    .post<AuthTokens>(
      '/api/v1/auth/token/refresh',
      refreshToken ? { refresh_token: refreshToken } : {},
      { headers: refreshHeaders() },
    )
    .then(({ data }) => {
      useAuthStore.getState().setTokens(data)
      return data.access_token
    })
    .catch(() => null)
    .finally(() => {
      refreshInFlight = null
    })
  return refreshInFlight
}

/** On page load, pick up the session from the refresh cookie (or this tab's
 * sessionStorage in an LMS frame). The access token is never stored. */
let restoring: Promise<void> | null = null
export function restoreSession(): Promise<void> {
  // An LMS launch (or SSO return) signs in with its own one-time code: never let an
  // older session from the cookie take its place
  if (window.location.pathname === '/launch') {
    useAuthStore.getState().setStatus('signed_out')
    return Promise.resolve()
  }
  restoring ??= refreshAccessToken().then((token) => {
    if (!token && !useAuthStore.getState().token) useAuthStore.getState().setStatus('signed_out')
  })
  return restoring
}

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean }

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined
    const path = window.location.pathname
    // The public student view is never authenticated, and a 401 from a sign-in
    // call (password login, LTI code exchange) is shown by the page that made it.
    const isLoginCall = config?.url === '/auth/local/login' || config?.url === '/auth/lti/exchange'
    if (
      error.response?.status !== 401 ||
      !config ||
      isLoginCall ||
      path.startsWith('/public/') ||
      path === '/login'
    ) {
      return Promise.reject(error)
    }

    // Access token expired: refresh once and retry the original request
    if (!config._retried) {
      config._retried = true
      const newToken = await refreshAccessToken()
      if (newToken) {
        config.headers.Authorization = `Bearer ${newToken}`
        return apiClient(config)
      }
    }

    // Refresh failed or the retry was also rejected: sign out
    useAuthStore.getState().clear()
    window.location.href = '/login'
    return Promise.reject(error)
  }
)

export default apiClient
