import type { Citation } from '@/api/hooks/useLists'

/** Library records the catalogue sync has flagged: staff should replace or unlink them */
export const NEEDS_ATTENTION: Record<string, { badge: string; explanation: string }> = {
  missing: {
    badge: 'Removed from catalogue',
    explanation:
      "This record is no longer in your library's catalogue, so its details won't update and its link may not work.",
  },
  suppressed: {
    badge: 'Hidden in catalogue',
    explanation: "This record is hidden in your library's catalogue, so students can't find it there.",
  },
}

export const needsAttention = (citation: Pick<Citation, 'source_status'>) =>
  Boolean(citation.source_status && citation.source_status in NEEDS_ATTENTION)
