import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '@/api/client'

export interface ExtensionConnection {
  id: string
  name: string
  created_at: string
  last_used_at?: string | null
}

export function useExtensionConnections() {
  return useQuery({
    queryKey: ['extension', 'tokens'],
    queryFn: async () => {
      const { data } = await apiClient.get<ExtensionConnection[]>('/extension/tokens')
      return data
    },
  })
}

export function useConnectExtension() {
  return useMutation({
    mutationFn: async (browser: string) => {
      const { data } = await apiClient.post<ExtensionConnection & { token: string }>('/extension/tokens', { browser })
      return data
    },
  })
}

export function useDisconnectExtension() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/extension/tokens/${id}`)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['extension', 'tokens'] }),
  })
}
