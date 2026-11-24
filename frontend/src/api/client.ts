import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore, type AuthTokens } from '@/stores/auth'

export const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

// Attach auth token to every request
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/**
 * One in-flight refresh shared by every request that hits a 401 at the same time,
 * so a page firing several queries doesn't trigger several refreshes.
 */
let refreshInFlight: Promise<string | null> | null = null

function refreshAccessToken(): Promise<string | null> {
  const refreshToken = useAuthStore.getState().refreshToken
  if (!refreshToken) return Promise.resolve(null)

  refreshInFlight ??= axios
    .post<AuthTokens>('/api/v1/auth/token/refresh', { refresh_token: refreshToken })
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

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean }

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined
    const path = window.location.pathname
    // The public student view is never authenticated, and a 401 from the login
    // call means bad credentials, which the login form shows itself.
    const isLoginCall = config?.url === '/auth/local/login'
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
