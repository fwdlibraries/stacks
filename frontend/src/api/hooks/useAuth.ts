import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../client'
import { useAuthStore, type AuthTokens } from '@/stores/auth'

export interface LoginCredentials {
  email: string
  password: string
}

interface LoginResponse extends AuthTokens {
  token_type: 'bearer'
  expires_in: number
}

export interface CurrentUser {
  id: string
  email: string
  display_name: string
  is_system_admin: boolean
  must_change_password: boolean
  organization: { id: string; name: string; slug: string }
}

export function useLogin() {
  const setTokens = useAuthStore((s) => s.setTokens)
  return useMutation({
    mutationFn: async (credentials: LoginCredentials) => {
      const { data } = await apiClient.post<LoginResponse>('/auth/local/login', credentials)
      return data
    },
    onSuccess: (data) => setTokens(data),
  })
}

export function useCurrentUser() {
  const token = useAuthStore((s) => s.token)
  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: async () => {
      const { data } = await apiClient.get<CurrentUser>('/auth/me')
      return data
    },
    enabled: Boolean(token),
    staleTime: 5 * 60_000,
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
