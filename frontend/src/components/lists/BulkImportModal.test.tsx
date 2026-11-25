import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { BulkImportModal } from './BulkImportModal'
import { renderRoutes } from '@/test/renderWithProviders'
import apiClient from '@/api/client'

afterEach(() => vi.restoreAllMocks())

const SECTIONS = [
  { id: 's1', title: 'Required', sort_order: 0, citations: [] },
  { id: 's2', title: 'Week 1', sort_order: 1, citations: [] },
]

const candidate = (system: string, title: string, confidence: number) => ({
  source_system: system,
  source_identifier: `${system}-${title}`,
  match_method: 'search',
  confidence,
  authoritative: system === 'alma',
  citation: { title, author: [], editor: [], year: 1961, metadata: {} },
})

const REVIEW = {
  id: 'j1',
  status: 'awaiting_review',
  total: 3,
  matched: 3,
  section_id: 's2',
  good_match: 0.85,
  items: [
    { id: 'i1', status: 'pending_review', text: 'Carr (1961) What is history?', structured: false, entry: { author: [] },
      candidates: [candidate('alma', 'What is history?', 0.97)], confidence: 0.97, warnings: [] },
    { id: 'i2', status: 'pending_review', text: 'Bloch. The Historian’s Craft. 1953.', structured: false, entry: { author: [] },
      candidates: [candidate('primo', 'The Historian’s Craft', 0.72)], confidence: 0.72, warnings: [] },
    { id: 'i3', status: 'pending_review', text: 'Nobody (2019) Nothing at all.', structured: false, entry: { author: [] },
      candidates: [], confidence: 0, warnings: [] },
  ],
}

describe('BulkImportModal', () => {
  it('starts an import, shows matches for review, and adds the chosen ones', async () => {
    const post = vi.spyOn(apiClient, 'post').mockImplementation(async (url: string) => {
      if (url === '/lists/l1/imports') return { data: { ...REVIEW, status: 'queued', matched: 0, items: [] } }
      return { data: { added: 2, skipped: 1, failed: [] } }
    })
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: REVIEW })
    const onDone = vi.fn()
    renderRoutes(
      [{ path: '/', element: <BulkImportModal listId="l1" sections={SECTIONS} onDone={onDone} onCancel={() => {}} /> }],
      '/'
    )

    fireEvent.change(screen.getByLabelText(/^References/), { target: { value: 'Carr (1961) What is history?' } })
    fireEvent.change(screen.getByLabelText(/^Add to section/), { target: { value: 's2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find matches' }))
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/lists/l1/imports', { text: 'Carr (1961) What is history?', section_id: 's2' })
    )

    // Good matches are preselected; possible matches and misses default to "as entered"
    const carr = await screen.findByRole('combobox', { name: /Carr \(1961\)/ })
    expect(carr).toHaveValue('match:0')
    const bloch = screen.getByRole('combobox', { name: /Bloch/ })
    expect(bloch).toHaveValue('as_entered')
    expect(bloch.closest('tr')).toHaveClass('table-warning')
    expect(within(bloch).getByRole('option', { name: /Library search: The Historian’s Craft \(1961\) · 72% match/ })).toBeInTheDocument()

    fireEvent.change(bloch, { target: { value: 'match:0' } })
    fireEvent.change(screen.getByRole('combobox', { name: /Nobody/ }), { target: { value: 'skip' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add 2 citations' }))

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/imports/j1/add', {
        items: [
          { id: 'i1', choice: 'match', candidate_index: 0 },
          { id: 'i2', choice: 'match', candidate_index: 0 },
          { id: 'i3', choice: 'skip' },
        ],
      })
    )
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('Added 2 citations, skipped 1.'))
  })
})
