import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../client'
import type { OrderPlan } from '@/lib/listOrder'

// ── Types (will be auto-generated from OpenAPI spec via generate-types script) ──

export type ResourceType =
  | 'book'
  | 'book_chapter'
  | 'journal_article'
  | 'ebook'
  | 'av_media'
  | 'website'
  | 'uploaded_file'
  | 'other'

export interface Citation {
  id: string
  title: string
  resource_type: ResourceType
  author?: string[] | null
  editor?: string[] | null
  year?: number | null
  publisher?: string | null
  place_of_publication?: string | null
  edition?: string | null
  volume?: string | null
  issue?: string | null
  pages?: string | null
  isbn?: string | null
  issn?: string | null
  doi?: string | null
  url?: string | null
  openurl?: string | null
  link_resolver_url?: string | null
  use_doi_for_linking: boolean
  /** Built per request from the library's discovery settings; never stored */
  link_url?: string | null
  link_kind?: 'library_record' | 'full_text' | 'doi' | 'web' | null
  student_note?: string | null
  /** Only returned to staff; never present on public list responses */
  staff_note?: string | null
  is_required: boolean
  sort_order: number
  metadata: Record<string, unknown>
  /** Staff only. Bound: bibliographic fields come from the library's system and are read-only */
  is_bound?: boolean
  source_system?: string | null
  source_identifier?: string | null
  /** 'ok' | 'missing' | 'unavailable' (set by sync) | 'unlinked' */
  source_status?: string | null
  source_synced_at?: string | null
}

export interface ListSection {
  id: string
  title: string
  description?: string | null
  sort_order: number
  citations: Citation[]
}

export type Visibility = 'public' | 'institution' | 'unlisted'

export interface ReadingListSummary {
  id: string
  title: string
  description?: string | null
  visibility: Visibility
  is_published: boolean
  updated_at?: string
  /** What the current user may do with it, from their roles */
  can_edit?: boolean
  can_publish?: boolean
  /** May copy it into another term (needs the whole course, not one offering) */
  can_copy?: boolean
  /** 'course': shared by every term; 'section': one term's own list; 'primary' */
  kind?: ListKind
  term?: TermRef | null
  section?: string | null
  copied_from?: { id: string; title: string; kind: ListKind; term_name?: string | null } | null
  copied_at?: string | null
}

export type ListKind = 'course' | 'section' | 'primary'

export interface TermRef {
  code: string
  name: string
}

export interface Term extends TermRef {
  id: string
  starts_on?: string | null
  ends_on?: string | null
}

export interface ReadingList extends ReadingListSummary {
  sections: ListSection[]
}

// ── Queries ────────────────────────────────────────────────────────────────────

/** Reading lists visible to the current user */
export function useReadingLists() {
  return useQuery({
    queryKey: ['lists'],
    queryFn: async () => {
      const { data } = await apiClient.get<ReadingListSummary[]>('/lists')
      return data
    },
  })
}

export function useReadingList(listId: string) {
  return useQuery({
    queryKey: ['lists', listId],
    queryFn: async () => {
      const { data } = await apiClient.get<ReadingList>(`/lists/${listId}`)
      return data
    },
  })
}

/** Compound document — fetches list + all sections + all citations in one request */
export function useReadingListFull(listId: string) {
  return useQuery({
    queryKey: ['lists', listId, 'full'],
    queryFn: async () => {
      const { data } = await apiClient.get<ReadingList>(`/lists/${listId}/full`)
      return data
    },
  })
}

/** The organization's terms, newest first */
export function useTerms(enabled = true) {
  return useQuery({
    queryKey: ['terms'],
    enabled,
    queryFn: async () => {
      const { data } = await apiClient.get<Term[]>('/terms')
      return data
    },
  })
}

/** Copy a list into another term (and optionally a section) of the same course */
export function useCopyList(listId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { term_id: string; section?: string | null }) => {
      const { data } = await apiClient.post<ReadingListSummary>(`/lists/${listId}/copy`, input)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['lists'] }),
  })
}

/** Public list view — no auth required, resolved by course code */
export function usePublicList(orgSlug: string, courseCode: string, term: string) {
  return useQuery({
    queryKey: ['public', 'lists', orgSlug, courseCode, term],
    queryFn: async () => {
      const { data } = await apiClient.get<ReadingList>(
        `/public/lists/${orgSlug}/${courseCode}/${term}`
      )
      return data
    },
  })
}

// ── Mutations ──────────────────────────────────────────────────────────────────

/** Editable citation fields, as sent to the API (blank strings are stored as null) */
export type CitationInput = Partial<
  Pick<
    Citation,
    | 'resource_type'
    | 'title'
    | 'is_required'
    | 'author'
    | 'year'
    | 'publisher'
    | 'edition'
    | 'volume'
    | 'issue'
    | 'pages'
    | 'isbn'
    | 'doi'
    | 'url'
    | 'student_note'
    | 'staff_note'
  >
>

export interface SectionInput {
  title?: string
  description?: string | null
}

export interface ListDetailsInput {
  title?: string
  description?: string | null
  visibility?: Visibility
}

/**
 * Mutation that refreshes every list query afterwards ('lists' prefix covers the
 * index, the full list and the summary).
 */
export function useListMutation<TVars, TData = unknown>(mutationFn: (vars: TVars) => Promise<TData>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['lists'] }),
  })
}

export function useSetPublished(listId: string) {
  return useListMutation(async (published: boolean) => {
    const { data } = await apiClient.post<ReadingListSummary>(
      `/lists/${listId}/${published ? 'publish' : 'unpublish'}`
    )
    return data
  })
}

export function useUpdateList(listId: string) {
  return useListMutation(async (input: ListDetailsInput) => {
    const { data } = await apiClient.patch<ReadingListSummary>(`/lists/${listId}`, input)
    return data
  })
}

export function useCreateSection(listId: string) {
  return useListMutation(async (input: SectionInput) => {
    const { data } = await apiClient.post<ListSection>(`/lists/${listId}/sections`, input)
    return data
  })
}

export function useUpdateSection() {
  return useListMutation(async ({ id, ...input }: SectionInput & { id: string }) => {
    const { data } = await apiClient.patch<ListSection>(`/sections/${id}`, input)
    return data
  })
}

export function useDeleteSection() {
  return useListMutation(async (sectionId: string) => {
    await apiClient.delete(`/sections/${sectionId}`)
  })
}

export function useCreateCitation() {
  return useListMutation(
    async ({ sectionId, ...input }: CitationInput & { sectionId: string }) => {
      const { data } = await apiClient.post<Citation>(`/sections/${sectionId}/citations`, input)
      return data
    }
  )
}

export function useUpdateCitation() {
  return useListMutation(async ({ id, ...input }: CitationInput & { id: string }) => {
    const { data } = await apiClient.patch<Citation>(`/citations/${id}`, input)
    return data
  })
}

/** Detach a citation from its library record so its fields can be edited */
export function useUnlinkCitation() {
  return useListMutation(async (citationId: string) => {
    const { data } = await apiClient.post<Citation>(`/citations/${citationId}/unlink`)
    return data
  })
}

export function useDeleteCitation() {
  return useListMutation(async (citationId: string) => {
    await apiClient.delete(`/citations/${citationId}`)
  })
}

/**
 * Apply a drag-and-drop reorder: update the cache immediately, send the change,
 * roll back if the server rejects it, and re-sync with the server either way.
 */
export function useApplyOrder(listId: string) {
  const queryClient = useQueryClient()
  const key = ['lists', listId, 'full']
  return useMutation({
    mutationFn: async ({ change }: OrderPlan) => {
      switch (change.kind) {
        case 'sections':
          await apiClient.post(`/lists/${listId}/sections/reorder`, { section_ids: change.sectionIds })
          break
        case 'citations':
          await apiClient.post(`/sections/${change.sectionId}/citations/reorder`, {
            citation_ids: change.citationIds,
          })
          break
        case 'move':
          // The move appends to the target section; the reorder then places it
          await apiClient.patch(`/citations/${change.citationId}`, { list_section_id: change.toSectionId })
          await apiClient.post(`/sections/${change.toSectionId}/citations/reorder`, {
            citation_ids: change.toCitationIds,
          })
          break
      }
    },
    onMutate: async ({ next }: OrderPlan) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<ReadingList>(key)
      queryClient.setQueryData(key, next)
      return { previous }
    },
    onError: (_error, _plan, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous)
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['lists'] }),
  })
}
