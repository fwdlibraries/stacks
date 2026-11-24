import { useMutation } from '@tanstack/react-query'
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

export const SOURCE_LABELS: Record<string, string> = {
  alma: 'Your library',
  crossref: 'Crossref',
  openlibrary: 'Open Library',
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
