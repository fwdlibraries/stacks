import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import RolloverView from './RolloverView'
import { renderRoutes } from '@/test/renderWithProviders'
import apiClient from '@/api/client'

const TERMS = [{ id: 't1', code: '202710', name: 'Fall 2027', starts_on: null, ends_on: null }]
const SEM_F2F = { id: 'p1', code: 'GEO101_F2F_SEM_PRIMARY', name: null, course: 'GEO101', mode: 'F2F', length: 'SEM',
  lms_org_unit_id: null, origin: 'import', has_list: false }
const SEM_OL = { ...SEM_F2F, id: 'p2', code: 'GEO101_OL_SEM_PRIMARY', mode: 'OL' }
const ITEM = {
  id: 'i1', section: '40113', lms_code: '40113.202710', course: 'GEO101', course_name: 'Physical Geography',
  department: 'GEO', instructors: [], part_of_term: 'FULL', length: 'SEM', mode: null, primary: null,
  match_source: null, file_primary_code: null, status: 'needs_source',
  problems: ['Several primaries fit: GEO101_F2F_SEM_PRIMARY, GEO101_OL_SEM_PRIMARY'], notes: null, decided_at: null,
}
const ITEMS = {
  term: TERMS[0], items: [ITEM], total: 1, problems: 1,
  counts: { needs_source: 1, in_review: 4, approved: 2, skipped: 0 },
}
const SETTINGS = { primary_code_pattern: '{subject}{number}_{mode}_{length}_PRIMARY', course_column: 'SEARCH_ID1',
  part_of_term_column: 'Term1', lengths: { FULL: 'SEM' }, section_code_pattern: '{crn}.{term}' }

function mockGet() {
  return vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) => {
    if (url === '/terms') return { data: TERMS }
    if (url === '/admin/rollover/settings') return { data: SETTINGS }
    if (url === '/admin/rollover/remembered') return { data: [] }
    if (url === '/admin/rollover/primaries') return { data: [SEM_F2F, SEM_OL] }
    if (url.endsWith('/items')) return { data: ITEMS }
    throw new Error(`unexpected GET ${url}`)
  })
}

const routes = [{ path: '/admin/rollover', element: <RolloverView /> }]

afterEach(() => vi.restoreAllMocks())

describe('RolloverView', () => {
  it('opens on the needs-a-source queue, with counts and problems', async () => {
    const get = mockGet()
    renderRoutes(routes, '/admin/rollover')

    expect(await screen.findByText('40113.202710')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Needs a source 1/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /In review 4/ })).toBeInTheDocument()
    expect(screen.getByText(/Several primaries fit/)).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/admin/rollover/terms/t1/items', { params: { status: 'needs_source' } })
  })

  it('chooses a primary and remembers it', async () => {
    mockGet()
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: { ...ITEM, primary: SEM_OL } })
    renderRoutes(routes, '/admin/rollover')

    fireEvent.click(await screen.findByRole('button', { name: 'Choose primary for 40113.202710' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(await within(dialog).findByLabelText(/GEO101_OL_SEM_PRIMARY/))
    expect(within(dialog).getByLabelText(/Use this primary for GEO101 \(SEM\)/)).toBeChecked()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith('/admin/rollover/items/i1', { set_primary: true, primary_id: 'p2', remember: true })
    )
  })
})
