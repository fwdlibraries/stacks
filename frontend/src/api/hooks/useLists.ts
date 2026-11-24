import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../client'

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
  student_note?: string | null
  /** Only returned to staff; never present on public list responses */
  staff_note?: string | null
  is_required: boolean
  sort_order: number
  metadata: Record<string, unknown>
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
function useListMutation<TVars, TData = unknown>(mutationFn: (vars: TVars) => Promise<TData>) {
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

export function useDeleteCitation() {
  return useListMutation(async (citationId: string) => {
    await apiClient.delete(`/citations/${citationId}`)
  })
}

export function useReorderSections(listId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (sectionIds: string[]) => {
      const { data } = await apiClient.post(`/lists/${listId}/sections/reorder`, { section_ids: sectionIds })
      return data
    },
    onMutate: async (sectionIds) => {
      // Optimistic update
      await queryClient.cancelQueries({ queryKey: ['lists', listId, 'full'] })
      const previous = queryClient.getQueryData(['lists', listId, 'full'])
      queryClient.setQueryData(['lists', listId, 'full'], (old: ReadingList) => ({
        ...old,
        sections: sectionIds.map((id, i) => ({
          ...old.sections.find((s) => s.id === id)!,
          sort_order: i,
        })),
      }))
      return { previous }
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['lists', listId, 'full'], context.previous)
      }
    },
  })
}
