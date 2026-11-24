import axios, { AxiosError } from 'axios'

export const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

// Attach auth token to every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('stacks_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Normalize error shape
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ error: { code: string; message: string } }>) => {
    // Token expired: clear it and send the user to sign in. Skip this on the
    // public student view (never authenticated) and on /login itself, where a
    // 401 means wrong credentials and the form shows the error.
    const path = window.location.pathname
    if (error.response?.status === 401 && !path.startsWith('/public/') && path !== '/login') {
      localStorage.removeItem('stacks_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default apiClient
