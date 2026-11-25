import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '@/api/client'
import type { LinkCheckResult } from '@/api/hooks/useLinks'

export interface Domain {
  id: string
  hostname: string
  is_primary: boolean
}

export interface OrganizationSettings {
  id: string
  name: string
  slug: string
  /** Where people reach this organization's Stacks */
  address: string
  domains: Domain[]
  /** null: using the installation default */
  lms_origins: string[] | null
  default_lms_origins: string[]
  contact_email: string | null
  default_contact_email: string | null
  can_manage_domains: boolean
}

export type OrganizationUpdate = Partial<Pick<OrganizationSettings, 'name' | 'lms_origins' | 'contact_email'>>

export type SourceKind = 'alma' | 'primo' | 'libkey'

export interface LibrarySource {
  kind: SourceKind
  configured: boolean
  is_active: boolean
  config: Record<string, unknown>
  key_set: boolean
  updated_at?: string | null
}

export interface TestResult {
  ok: boolean
  message: string
}

export type StepName = 'libkey' | 'alma' | 'open_access'

export interface LinkResolutionSettings {
  stack: StepName[]
  cache_ttl_seconds: number
  step_timeout_seconds: number
  available: Record<StepName, boolean>
}

const ORG = ['admin', 'organization']
const SOURCES = ['admin', 'sources']
const LINKS = ['admin', 'link-resolution']

export function useOrganizationSettings() {
  return useQuery({
    queryKey: ORG,
    queryFn: async () => (await apiClient.get<OrganizationSettings>('/admin/organization')).data,
  })
}

/** Mutations that answer with the whole organization: update the cache from the answer */
function useOrgMutation<V>(fn: (vars: V) => Promise<OrganizationSettings>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => {
      queryClient.setQueryData(ORG, data)
      // The organization's name shows in the header
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
    },
  })
}

export function useUpdateOrganization() {
  return useOrgMutation(async (input: OrganizationUpdate) => (await apiClient.patch('/admin/organization', input)).data)
}

export function useAddDomain() {
  return useOrgMutation(
    async (hostname: string) => (await apiClient.post('/admin/organization/domains', { hostname })).data
  )
}

export function useMakeDomainPrimary() {
  return useOrgMutation(async (id: string) => (await apiClient.post(`/admin/organization/domains/${id}/primary`)).data)
}

export function useRemoveDomain() {
  return useOrgMutation(async (id: string) => (await apiClient.delete(`/admin/organization/domains/${id}`)).data)
}

export function useLibrarySources() {
  return useQuery({
    queryKey: SOURCES,
    queryFn: async () => (await apiClient.get<LibrarySource[]>('/admin/sources')).data,
  })
}

export interface SourceInput {
  config: Record<string, unknown>
  /** Write-only; omit to keep the stored key */
  api_key?: string
  is_active?: boolean
}

export function useSaveSource(kind: SourceKind) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: SourceInput) => (await apiClient.put<LibrarySource>(`/admin/sources/${kind}`, input)).data,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SOURCES })
      queryClient.invalidateQueries({ queryKey: LINKS }) // which steps are available
    },
  })
}

export function useRemoveSource(kind: SourceKind) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await apiClient.delete(`/admin/sources/${kind}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SOURCES })
      queryClient.invalidateQueries({ queryKey: LINKS })
    },
  })
}

export function useTestSource(kind: SourceKind) {
  return useMutation({
    mutationFn: async (input: Partial<SourceInput>) =>
      (await apiClient.post<TestResult>(`/admin/sources/${kind}/test`, input)).data,
  })
}

export function useLinkResolutionSettings() {
  return useQuery({
    queryKey: LINKS,
    queryFn: async () => (await apiClient.get<LinkResolutionSettings>('/admin/link-resolution')).data,
  })
}

export function useSaveLinkResolution() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: Omit<LinkResolutionSettings, 'available'>) =>
      (await apiClient.put<LinkResolutionSettings>('/admin/link-resolution', input)).data,
    onSuccess: (data) => queryClient.setQueryData(LINKS, data),
  })
}

export function useTryLinkResolution() {
  return useMutation({
    mutationFn: async (query: string) =>
      (await apiClient.post<LinkCheckResult>('/admin/link-resolution/try', { query })).data,
  })
}
