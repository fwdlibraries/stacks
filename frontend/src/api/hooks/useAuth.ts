import { useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../client'
import { useAuthStore } from '@/stores/auth'

export interface LoginCredentials {
  username: string
  password: string
}

// Assumed response shape; POST /auth/local/login is still a stub on the backend.
// Replace with the generated type once `npm run generate-types` covers it.
interface LoginResponse {
  access_token: string
  refresh_token?: string
}

export function useLogin() {
  const setToken = useAuthStore((s) => s.setToken)
  return useMutation({
    mutationFn: async (credentials: LoginCredentials) => {
      const { data } = await apiClient.post<LoginResponse>('/auth/local/login', credentials)
      return data
    },
    onSuccess: (data) => setToken(data.access_token),
  })
}

export function useLogout() {
  const clear = useAuthStore((s) => s.clear)
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await apiClient.post('/auth/logout')
    },
    // Clear local state even if the server call fails
    onSettled: () => {
      clear()
      queryClient.clear()
    },
  })
}
