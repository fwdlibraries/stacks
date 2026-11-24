/**
 * Pure ordering logic for drag-and-drop in the list editor. Each planner returns
 * the reordered list (for an optimistic update) plus the change to send to the
 * API, or null when the drop changes nothing.
 */
import { arrayMove } from '@dnd-kit/sortable'
import type { Citation, ListSection, ReadingList } from '@/api/hooks/useLists'

export type OrderChange =
  | { kind: 'sections'; sectionIds: string[] }
  | { kind: 'citations'; sectionId: string; citationIds: string[] }
  | { kind: 'move'; citationId: string; toSectionId: string; toCitationIds: string[] }

export interface OrderPlan {
  next: ReadingList
  change: OrderChange
}

/** Where a dragged citation was dropped: on another citation, or on a section's empty area */
export interface CitationDropTarget {
  sectionId: string
  citationId?: string
}

const withSortOrder = <T extends { sort_order: number }>(items: T[]): T[] =>
  items.map((item, index) => ({ ...item, sort_order: index }))

export function planSectionMove(list: ReadingList, activeId: string, overId: string): OrderPlan | null {
  const from = list.sections.findIndex((s) => s.id === activeId)
  const to = list.sections.findIndex((s) => s.id === overId)
  if (from === -1 || to === -1 || from === to) return null

  const sections = withSortOrder(arrayMove(list.sections, from, to))
  return {
    next: { ...list, sections },
    change: { kind: 'sections', sectionIds: sections.map((s) => s.id) },
  }
}

export function findCitationSection(list: ReadingList, citationId: string): ListSection | undefined {
  return list.sections.find((s) => s.citations.some((c) => c.id === citationId))
}

export function planCitationDrop(
  list: ReadingList,
  citationId: string,
  target: CitationDropTarget
): OrderPlan | null {
  const source = findCitationSection(list, citationId)
  const dest = list.sections.find((s) => s.id === target.sectionId)
  if (!source || !dest || target.citationId === citationId) return null

  const fromIndex = source.citations.findIndex((c) => c.id === citationId)
  const moved = source.citations[fromIndex]

  // Same section: a plain reorder
  if (source.id === dest.id) {
    const toIndex = target.citationId
      ? dest.citations.findIndex((c) => c.id === target.citationId)
      : dest.citations.length - 1
    if (toIndex === -1 || toIndex === fromIndex) return null
    const citations = withSortOrder(arrayMove(dest.citations, fromIndex, toIndex))
    return {
      next: replaceSections(list, { ...dest, citations }),
      change: { kind: 'citations', sectionId: dest.id, citationIds: citations.map((c) => c.id) },
    }
  }

  // Another section: insert before the citation dropped on, or at the end
  const overIndex = target.citationId ? dest.citations.findIndex((c) => c.id === target.citationId) : -1
  const insertAt = overIndex === -1 ? dest.citations.length : overIndex
  const destCitations: Citation[] = [...dest.citations]
  destCitations.splice(insertAt, 0, moved)

  const newSource = { ...source, citations: withSortOrder(source.citations.filter((c) => c.id !== citationId)) }
  const newDest = { ...dest, citations: withSortOrder(destCitations) }
  return {
    next: replaceSections(list, newSource, newDest),
    change: {
      kind: 'move',
      citationId,
      toSectionId: dest.id,
      toCitationIds: newDest.citations.map((c) => c.id),
    },
  }
}

function replaceSections(list: ReadingList, ...updated: ListSection[]): ReadingList {
  const byId = new Map(updated.map((s) => [s.id, s]))
  return { ...list, sections: list.sections.map((s) => byId.get(s.id) ?? s) }
}
