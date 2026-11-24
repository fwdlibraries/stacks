import { describe, expect, it } from 'vitest'
import { planCitationDrop, planSectionMove } from './listOrder'
import type { Citation, ReadingList } from '@/api/hooks/useLists'

const cite = (id: string, sort_order: number): Citation => ({
  id,
  title: id.toUpperCase(),
  resource_type: 'book',
  use_doi_for_linking: true,
  is_required: true,
  sort_order,
  metadata: {},
})

const LIST: ReadingList = {
  id: 'l',
  title: 'L',
  visibility: 'public',
  is_published: true,
  sections: [
    { id: 's1', title: 'Required', sort_order: 0, citations: [cite('a', 0), cite('b', 1), cite('c', 2)] },
    { id: 's2', title: 'Week 1', sort_order: 1, citations: [cite('d', 0)] },
    { id: 's3', title: 'Empty', sort_order: 2, citations: [] },
  ],
}

const ids = (list: ReadingList, sectionIndex: number) => list.sections[sectionIndex].citations.map((c) => c.id)
const orders = (list: ReadingList, sectionIndex: number) =>
  list.sections[sectionIndex].citations.map((c) => c.sort_order)

describe('planSectionMove', () => {
  it('moves a section and renumbers sort_order', () => {
    const plan = planSectionMove(LIST, 's3', 's1')!
    expect(plan.change).toEqual({ kind: 'sections', sectionIds: ['s3', 's1', 's2'] })
    expect(plan.next.sections.map((s) => s.sort_order)).toEqual([0, 1, 2])
  })

  it('returns null when nothing changes', () => {
    expect(planSectionMove(LIST, 's1', 's1')).toBeNull()
    expect(planSectionMove(LIST, 'nope', 's1')).toBeNull()
  })
})

describe('planCitationDrop', () => {
  it('reorders within a section', () => {
    const plan = planCitationDrop(LIST, 'a', { sectionId: 's1', citationId: 'c' })!
    expect(plan.change).toEqual({ kind: 'citations', sectionId: 's1', citationIds: ['b', 'c', 'a'] })
    expect(orders(plan.next, 0)).toEqual([0, 1, 2])
  })

  it('moves to the end when dropped on its own section area', () => {
    const plan = planCitationDrop(LIST, 'a', { sectionId: 's1' })!
    expect(ids(plan.next, 0)).toEqual(['b', 'c', 'a'])
  })

  it('moves to another section before the citation it was dropped on', () => {
    const plan = planCitationDrop(LIST, 'b', { sectionId: 's2', citationId: 'd' })!
    expect(plan.change).toEqual({ kind: 'move', citationId: 'b', toSectionId: 's2', toCitationIds: ['b', 'd'] })
    expect(ids(plan.next, 0)).toEqual(['a', 'c'])
    expect(orders(plan.next, 0)).toEqual([0, 1])
    expect(ids(plan.next, 1)).toEqual(['b', 'd'])
  })

  it('moves into an empty section', () => {
    const plan = planCitationDrop(LIST, 'd', { sectionId: 's3' })!
    expect(plan.change).toEqual({ kind: 'move', citationId: 'd', toSectionId: 's3', toCitationIds: ['d'] })
    expect(ids(plan.next, 1)).toEqual([])
  })

  it('returns null for no-op drops', () => {
    expect(planCitationDrop(LIST, 'a', { sectionId: 's1', citationId: 'a' })).toBeNull()
    expect(planCitationDrop(LIST, 'c', { sectionId: 's1' })).toBeNull() // already last
    expect(planCitationDrop(LIST, 'zzz', { sectionId: 's1' })).toBeNull()
  })

  it('does not mutate the original list', () => {
    planCitationDrop(LIST, 'b', { sectionId: 's2', citationId: 'd' })
    expect(ids(LIST, 0)).toEqual(['a', 'b', 'c'])
    expect(ids(LIST, 1)).toEqual(['d'])
  })
})
