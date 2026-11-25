import { useMutation, useQuery } from '@tanstack/react-query'
import apiClient from '@/api/client'
import type { LookupCandidate } from '@/api/hooks/useIngest'
import { useListMutation } from '@/api/hooks/useLists'

export interface ImportItem {
  id: string
  status: string
  /** The entry as written (RIS/BibTeX record or pasted reference) */
  text: string
  /** False for pasted references: only identifiers and year are known */
  structured: boolean
  entry: { title?: string | null; author: string[]; year?: number | null; resource_type?: string | null }
  candidates: LookupCandidate[]
  confidence: number | null
  warnings: string[]
}

export interface ImportJob {
  id: string
  status: 'queued' | 'processing' | 'awaiting_review' | 'completed' | 'failed'
  total: number
  matched: number
  section_id: string
  error?: string | null
  /** Matches at or above this are preselected */
  good_match: number
  items: ImportItem[]
}

export type ItemChoice = { id: string; choice: 'match' | 'as_entered' | 'skip'; candidate_index?: number }

export function useStartImport(listId: string) {
  return useMutation({
    mutationFn: async (input: { text: string; section_id: string }) => {
      const { data } = await apiClient.post<ImportJob>(`/lists/${listId}/imports`, input)
      return data
    },
  })
}

const MATCHING = new Set(['queued', 'processing'])

/** Polls while the worker matches entries */
export function useImportJob(jobId: string | null) {
  return useQuery({
    queryKey: ['imports', jobId],
    queryFn: async () => {
      const { data } = await apiClient.get<ImportJob>(`/imports/${jobId}`)
      return data
    },
    enabled: Boolean(jobId),
    refetchInterval: (query) => (query.state.data && !MATCHING.has(query.state.data.status) ? false : 1500),
  })
}

export function useAddImport() {
  return useListMutation(async ({ jobId, items }: { jobId: string; items: ItemChoice[] }) => {
    const { data } = await apiClient.post<{ added: number; skipped: number; failed: { reason: string }[] }>(
      `/imports/${jobId}/add`,
      { items }
    )
    return data
  })
}
