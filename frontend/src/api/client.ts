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
    if (error.response?.status === 401) {
      // Token expired — clear and redirect to login
      localStorage.removeItem('stacks_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default apiClient
