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

// ── LMS ────────────────────────────────────────────────────────────────────

export interface LmsDeployment {
  id: string
  deployment_id: string
  label?: string | null
  is_active: boolean
}

export interface LmsPlatform {
  id: string
  issuer: string
  client_id: string
  auth_login_url: string
  auth_token_url: string
  jwks_url: string
  is_active: boolean
  created_at: string
  deployments: LmsDeployment[]
  people: number
}

export interface LmsSettings {
  tool: { login_url: string; redirect_url: string; target_link_uri: string; jwks_url: string }
  platforms: LmsPlatform[]
}

export interface LmsRegistration {
  issuer: string
  client_id: string
  auth_login_url: string
  auth_token_url: string
  jwks_url: string
  deployment_ids: string[]
}

const LMS = ['admin', 'lms']

export function useLmsSettings() {
  return useQuery({ queryKey: LMS, queryFn: async () => (await apiClient.get<LmsSettings>('/admin/lms')).data })
}

function useLmsMutation<V>(fn: (vars: V) => Promise<LmsSettings>) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: (data) => queryClient.setQueryData(LMS, data) })
}

export function useRegisterLms() {
  return useLmsMutation(async (input: LmsRegistration) => (await apiClient.post('/admin/lms', input)).data)
}

export function useUpdateLms() {
  return useLmsMutation(
    async ({ id, ...input }: { id: string } & Partial<Pick<LmsPlatform, 'is_active' | 'auth_login_url' | 'auth_token_url' | 'jwks_url'>>) =>
      (await apiClient.patch(`/admin/lms/${id}`, input)).data
  )
}

export function useAddDeployment() {
  return useLmsMutation(
    async ({ platformId, deployment_id }: { platformId: string; deployment_id: string }) =>
      (await apiClient.post(`/admin/lms/${platformId}/deployments`, { deployment_id })).data
  )
}

export function useRemoveDeployment() {
  return useLmsMutation(
    async ({ platformId, id }: { platformId: string; id: string }) =>
      (await apiClient.delete(`/admin/lms/${platformId}/deployments/${id}`)).data
  )
}

// ── People ─────────────────────────────────────────────────────────────────

export type ScopeType = 'organization' | 'college' | 'department' | 'course_template' | 'course_offering'

export interface Scope {
  type: ScopeType
  id: string
  label: string
}

export interface PersonRole {
  id: string
  role: string
  scope: Scope
  can_remove: boolean
}

export interface Person {
  id: string
  display_name: string
  email: string
  is_active: boolean
  is_system_admin: boolean
  from_lms: boolean
  has_password: boolean
  last_login_at?: string | null
  roles: PersonRole[]
}

export interface PeoplePage {
  people: Person[]
  total: number
  roles: string[]
  can_change_accounts: boolean
}

export const PEOPLE_PAGE_SIZE = 50

export function usePeople(q: string, offset: number) {
  return useQuery({
    queryKey: ['admin', 'people', q, offset],
    queryFn: async () =>
      (await apiClient.get<PeoplePage>('/admin/people', { params: { q: q || undefined, offset, limit: PEOPLE_PAGE_SIZE } })).data,
    placeholderData: (previous) => previous,
  })
}

export function useAssignableScopes() {
  return useQuery({ queryKey: ['admin', 'scopes'], queryFn: async () => (await apiClient.get<Scope[]>('/admin/scopes')).data })
}

function usePeopleMutation<V, R>(fn: (vars: V) => Promise<R>) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'people'] }) })
}

export function useGiveRole() {
  return usePeopleMutation(
    async ({ userId, ...input }: { userId: string; role: string; scope_type: ScopeType; scope_id: string }) =>
      (await apiClient.post(`/admin/people/${userId}/roles`, input)).data
  )
}

export function useTakeRole() {
  return usePeopleMutation(async ({ userId, id }: { userId: string; id: string }) => {
    await apiClient.delete(`/admin/people/${userId}/roles/${id}`)
  })
}

export function useSetAccountActive() {
  return usePeopleMutation(
    async ({ userId, is_active }: { userId: string; is_active: boolean }) =>
      (await apiClient.patch(`/admin/people/${userId}`, { is_active })).data
  )
}

// ── Reports ────────────────────────────────────────────────────────────────

interface CitationRow {
  citation_id: string
  title: string
  list_id: string
  list_title: string
  section_title: string
}

export interface Reports {
  window_days: number
  overview: {
    lists_published: number
    lists_draft: number
    citations: number
    library_records: number
    flagged: number
    clicks: number
    direct_clicks: number
  }
  sync: {
    connected: boolean
    last_run_at?: string | null
    last_status?: string | null
    checked?: number | null
    updated?: number | null
    flagged?: number | null
    error?: string | null
    can_run: boolean
  }
  flagged: (CitationRow & { status: string; since?: string | null })[]
  hard_to_reach: (CitationRow & { clicks: number; fallback_clicks: number })[]
  top_lists: { list_id: string; list_title: string; clicks: number }[]
  top_citations: (CitationRow & { clicks: number })[]
  imports: {
    id: string
    status: string
    created_at: string
    list_id?: string | null
    list_title?: string | null
    total: number
    added?: number | null
    by?: string | null
  }[]
}

export function useReports() {
  return useQuery({ queryKey: ['admin', 'reports'], queryFn: async () => (await apiClient.get<Reports>('/admin/reports')).data })
}

export function useSyncNow() {
  return useMutation({ mutationFn: async () => (await apiClient.post('/admin/sync')).data })
}

// ── Look and feel ──────────────────────────────────────────────────────────

export interface ThemeTokens {
  primary: string
  link: string
  background: string
  surface: string
  text: string
  border: string
  heading_font: string
  body_font: string
  corners: 'square' | 'standard' | 'rounded'
}

export interface ThemeSettings {
  mode: 'stacks' | 'lms' | 'custom'
  lms: 'auto' | 'brightspace' | 'canvas' | 'moodle'
  lms_primary: string | null
  tokens: ThemeTokens
  custom_css: string
}

export interface ThemeState extends ThemeSettings {
  has_logo: boolean
  warnings: string[]
  fonts: { key: string; label: string }[]
  lms_presets_ready: boolean
  /** The LMS this organization launches from, as "auto" matches it */
  detected_lms: string | null
}

const THEME = ['admin', 'theme']

export function useTheme() {
  return useQuery({ queryKey: THEME, queryFn: async () => (await apiClient.get<ThemeState>('/admin/theme')).data })
}

function useThemeMutation<V>(fn: (vars: V) => Promise<ThemeState>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => {
      queryClient.setQueryData(THEME, data)
      queryClient.invalidateQueries({ queryKey: ['tenant'] }) // logo and theme version
      // Re-load the site stylesheet so the change shows here at once
      document.querySelectorAll<HTMLLinkElement>('link[href^="/api/v1/tenant/theme.css"]').forEach((link) => {
        link.href = `/api/v1/tenant/theme.css?t=${Date.now()}`
      })
    },
  })
}

export function useSaveTheme() {
  return useThemeMutation(async (input: ThemeSettings) => (await apiClient.put('/admin/theme', input)).data)
}

export function useUploadLogo() {
  return useThemeMutation(
    async (input: { content_type: string; data: string }) => (await apiClient.put('/admin/theme/logo', input)).data
  )
}

export function useRemoveLogo() {
  return useThemeMutation(async () => (await apiClient.delete('/admin/theme/logo')).data)
}

export function usePreviewTheme() {
  return useMutation({
    mutationFn: async (input: ThemeSettings) =>
      (await apiClient.post<{ css: string; warnings: string[] }>('/admin/theme/preview', input)).data,
  })
}
