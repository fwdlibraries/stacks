import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import apiClient from '@/api/client'
import { useApplyOrder, type ReadingList } from './useLists'
import type { OrderPlan } from '@/lib/listOrder'

const BEFORE: ReadingList = {
  id: 'l1',
  title: 'L',
  visibility: 'public',
  is_published: true,
  sections: [
    { id: 's1', title: 'A', sort_order: 0, citations: [] },
    { id: 's2', title: 'B', sort_order: 1, citations: [] },
  ],
}
const AFTER: ReadingList = { ...BEFORE, sections: [BEFORE.sections[1], BEFORE.sections[0]] }

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  queryClient.setQueryData(['lists', 'l1', 'full'], BEFORE)
  vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  const { result } = renderHook(() => useApplyOrder('l1'), { wrapper })
  return { queryClient, result }
}

afterEach(() => vi.restoreAllMocks())

describe('useApplyOrder', () => {
  it('updates the cache immediately and posts the section order', async () => {
    let release!: () => void
    const post = vi
      .spyOn(apiClient, 'post')
      .mockImplementation(() => new Promise((resolve) => (release = () => resolve({ data: null }))))
    const { queryClient, result } = setup()

    act(() => result.current.mutate({ next: AFTER, change: { kind: 'sections', sectionIds: ['s2', 's1'] } }))

    await waitFor(() => expect(queryClient.getQueryData(['lists', 'l1', 'full'])).toEqual(AFTER))
    expect(post).toHaveBeenCalledWith('/lists/l1/sections/reorder', { section_ids: ['s2', 's1'] })
    release()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })

  it('moves a citation with a PATCH then a reorder of the target section', async () => {
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: null })
    const { result } = setup()
    const plan: OrderPlan = {
      next: AFTER,
      change: { kind: 'move', citationId: 'c1', toSectionId: 's2', toCitationIds: ['c1', 'c2'] },
    }

    await act(() => result.current.mutateAsync(plan))

    expect(patch).toHaveBeenCalledWith('/citations/c1', { list_section_id: 's2' })
    expect(post).toHaveBeenCalledWith('/sections/s2/citations/reorder', { citation_ids: ['c1', 'c2'] })
    expect(patch.mock.invocationCallOrder[0]).toBeLessThan(post.mock.invocationCallOrder[0])
  })

  it('rolls back when the server rejects the change', async () => {
    vi.spyOn(apiClient, 'post').mockRejectedValue(new Error('422'))
    const { queryClient, result } = setup()

    act(() => result.current.mutate({ next: AFTER, change: { kind: 'sections', sectionIds: ['s2', 's1'] } }))

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(queryClient.getQueryData(['lists', 'l1', 'full'])).toEqual(BEFORE)
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['lists'] })
  })
})
