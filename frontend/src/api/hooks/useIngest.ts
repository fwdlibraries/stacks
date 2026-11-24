import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query'
import apiClient from '@/api/client'
import { useListMutation, type Citation, type ResourceType } from '@/api/hooks/useLists'

/** A record found by lookup; adding it sends only the binding, never these fields */
export interface LookupCandidate {
  source_system: string
  source_identifier: string
  match_method: string
  confidence: number
  /** From the library's own system: added citations stay in sync with it */
  authoritative: boolean
  /** Search results only */
  availability?: Availability | null
  citation: {
    title?: string | null
    resource_type?: ResourceType | string | null
    author: string[]
    editor: string[]
    year?: number | null
    publisher?: string | null
    edition?: string | null
    isbn?: string | null
    doi?: string | null
    metadata: Record<string, unknown>
  }
}

export interface LookupResponse {
  identifiers: { kind: 'doi' | 'isbn' | 'mms_id'; value: string }[]
  candidates: LookupCandidate[]
  warnings: string[]
}

export type Availability = 'online' | 'in_library' | 'check_holdings' | 'citation_only'

export const AVAILABILITY_LABELS: Record<Availability, string> = {
  online: 'Online',
  in_library: 'In the library',
  check_holdings: 'Check holdings',
  citation_only: 'Citation only',
}

export const SOURCE_LABELS: Record<string, string> = {
  alma: 'Your library',
  primo: 'Library search',
  crossref: 'Crossref',
  openlibrary: 'Open Library',
}

export interface SearchResponse {
  total: number
  offset: number
  candidates: LookupCandidate[]
}

export const SEARCH_PAGE_SIZE = 10
// The API pages no deeper than this
const MAX_SEARCH_OFFSET = 2000

/** Which ways of adding citations this organization has set up */
export function useIngestCapabilities() {
  return useQuery({
    queryKey: ['ingest', 'capabilities'],
    queryFn: async () => {
      const { data } = await apiClient.get<{ library_search: boolean }>('/ingest/capabilities')
      return data
    },
    staleTime: 5 * 60_000,
  })
}

/** Keyword search of the library's discovery system, a page at a time */
export function useLibrarySearch(query: string) {
  return useInfiniteQuery({
    queryKey: ['ingest', 'search', query],
    enabled: query.length > 0,
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const { data } = await apiClient.post<SearchResponse>('/ingest/search', {
        query,
        offset: pageParam,
        limit: SEARCH_PAGE_SIZE,
      })
      return data
    },
    getNextPageParam: (last) => {
      const next = last.offset + SEARCH_PAGE_SIZE
      return next < last.total && next <= MAX_SEARCH_OFFSET ? next : undefined
    },
    staleTime: 60_000,
  })
}

export function useLookup() {
  return useMutation({
    mutationFn: async (query: string) => {
      const { data } = await apiClient.post<LookupResponse>('/ingest/lookup', { query })
      return data
    },
  })
}

export interface FromSourceInput {
  sectionId: string
  source_system: string
  source_identifier: string
  is_required?: boolean
  student_note?: string | null
  staff_note?: string | null
}

export function useCreateFromSource() {
  return useListMutation(async ({ sectionId, ...input }: FromSourceInput) => {
    const { data } = await apiClient.post<Citation>(`/sections/${sectionId}/citations/from-source`, input)
    return data
  })
}
