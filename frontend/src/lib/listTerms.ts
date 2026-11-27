import type { ReadingListSummary } from '@/api/hooks/useLists'

/** Which term(s) a list is for, for staff */
export function termLabel(list: ReadingListSummary): string {
  if (list.kind === 'primary') return 'Primary list'
  if (list.kind === 'section' && list.term) return list.section ? `${list.term.name} · ${list.section}` : list.term.name
  return 'All terms'
}
