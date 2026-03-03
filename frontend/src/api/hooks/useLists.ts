import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../client'

// ── Types (will be auto-generated from OpenAPI spec via generate-types script) ──

export interface Citation {
  id: string
  title: string
  resource_type: string
  author?: string[]
  year?: number
  publisher?: string
  doi?: string
  url?: string
  openurl?: string
  link_resolver_url?: string
  use_doi_for_linking: boolean
  student_note?: string
  is_required: boolean
  sort_order: number
  metadata: Record<string, unknown>
}

export interface ListSection {
  id: string
  title: string
  description?: string
  sort_order: number
  citations: Citation[]
}

export interface ReadingList {
  id: string
  title: string
  description?: string
  visibility: 'public' | 'institution' | 'unlisted'
  is_published: boolean
  sections: ListSection[]
}

// ── Queries ────────────────────────────────────────────────────────────────────

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

export function usePublishList(listId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.post(`/lists/${listId}/publish`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lists', listId] })
    },
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
