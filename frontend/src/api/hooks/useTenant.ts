import { useQuery } from '@tanstack/react-query'
import apiClient from '@/api/client'

export interface TenantInfo {
  name: string | null
  slug: string | null
  theme: { mode: 'stacks' | 'lms' | 'custom'; has_logo: boolean; version: string }
}

/** The organization this hostname serves, and its theme details (public) */
export function useTenant() {
  return useQuery({
    queryKey: ['tenant'],
    queryFn: async () => (await apiClient.get<TenantInfo>('/tenant')).data,
    staleTime: 5 * 60_000,
  })
}

/** The organization's logo URL (versioned, so a new logo isn't served from cache), or null */
export function logoUrl(tenant: TenantInfo | undefined): string | null {
  return tenant?.theme.has_logo ? `/api/v1/tenant/logo?v=${tenant.theme.version}` : null
}
