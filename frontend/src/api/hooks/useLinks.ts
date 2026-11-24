import { useMutation, useQuery } from '@tanstack/react-query'
import apiClient from '@/api/client'

export interface ClickCounts {
  total: number
  last_30_days: number
}

/** Anonymous click-through counts per citation (published lists only) */
export function useListClicks(listId: string) {
  return useQuery({
    queryKey: ['lists', listId, 'clicks'],
    queryFn: async () => {
      const { data } = await apiClient.get<{ citations: Record<string, ClickCounts> }>(`/lists/${listId}/clicks`)
      return data.citations
    },
    enabled: Boolean(listId),
    staleTime: 60_000,
  })
}

export interface LinkCheckStep {
  step: string
  outcome: 'found' | 'not_found' | 'error' | 'skipped'
  detail?: string | null
  url?: string | null
}

export interface LinkCheckResult {
  url: string | null
  resolved_by: string | null
  detail: string | null
  retracted: boolean
  steps: LinkCheckStep[]
}

/** Run the resolver stack now and report each step */
export function useLinkCheck() {
  return useMutation({
    mutationFn: async (citationId: string) => {
      const { data } = await apiClient.get<LinkCheckResult>(`/citations/${citationId}/link-check`)
      return data
    },
  })
}

export interface CitationEvent {
  occurred_at: string
  kind: 'updated' | 'missing' | 'suppressed' | 'restored' | string
  source_system?: string | null
  details: Record<string, [unknown, unknown]>
}

/** What the catalogue sync changed, newest first */
export function useCitationHistory(citationId: string | undefined) {
  return useQuery({
    queryKey: ['citations', citationId, 'history'],
    queryFn: async () => {
      const { data } = await apiClient.get<CitationEvent[]>(`/citations/${citationId}/history`)
      return data
    },
    enabled: Boolean(citationId),
  })
}
