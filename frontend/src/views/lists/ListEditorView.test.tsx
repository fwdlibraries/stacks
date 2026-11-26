import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import ListEditorView from './ListEditorView'
import { renderRoutes } from '@/test/renderWithProviders'
import apiClient from '@/api/client'
import type { ReadingList } from '@/api/hooks/useLists'

const LIST: ReadingList = {
  id: 'l1',
  title: 'HIST 101 Reading List',
  visibility: 'public',
  is_published: false,
  can_edit: true,
  can_publish: true,
  sections: [
    {
      id: 's1',
      title: 'Required',
      sort_order: 0,
      citations: [
        {
          id: 'c1',
          title: 'What Is History?',
          resource_type: 'book',
          author: ['Carr, Edward Hallett'],
          use_doi_for_linking: true,
          is_required: true,
          sort_order: 0,
          metadata: {},
        },
      ],
    },
    { id: 's2', title: 'Week 1', sort_order: 1, citations: [] },
  ],
}

const routes = [{ path: '/lists/:listId', element: <ListEditorView /> }]

beforeEach(() => {
  vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) =>
    url === '/ingest/capabilities' ? { data: { library_search: false } } : { data: LIST }
  )
})

afterEach(() => vi.restoreAllMocks())

describe('ListEditorView', () => {
  it('copies the list into another term and opens the copy', async () => {
    vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) => {
      if (url === '/ingest/capabilities') return { data: { library_search: false } }
      if (url === '/terms') return { data: [{ id: 't2', code: 'spring-2027', name: 'Spring 2027' }] }
      return { data: { ...LIST, can_copy: true, kind: 'course' } }
    })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { ...LIST, id: 'l2', kind: 'section' } })
    renderRoutes(routes, '/lists/l1')

    expect(await screen.findByText(/All terms/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Copy to another term' }))
    const dialog = await screen.findByRole('dialog')
    const term = within(dialog).getByLabelText(/^Term/)
    await within(dialog).findByRole('option', { name: /Spring 2027/ })
    fireEvent.change(term, { target: { value: 't2' } })
    fireEvent.change(within(dialog).getByLabelText(/^Section/), { target: { value: ' 40112 ' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Copy list' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/lists/l1/copy', { term_id: 't2', section: '40112' }))
  })

  it('shows which term a copy is for and where it came from', async () => {
    vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) =>
      url === '/ingest/capabilities'
        ? { data: { library_search: false } }
        : {
            data: {
              ...LIST,
              kind: 'section',
              term: { code: '202710', name: 'Fall 2027' },
              section: '40112',
              copied_from: { id: 'l0', title: 'HIST 101 Reading List', kind: 'course', term_name: null },
              copied_at: '2027-07-01T12:00:00Z',
            },
          }
    )
    renderRoutes(routes, '/lists/l1')

    expect(await screen.findByText(/Fall 2027 · 40112/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'HIST 101 Reading List' })).toHaveAttribute('href', '/lists/l0')
    // No copy permission: no button
    expect(screen.queryByRole('button', { name: 'Copy to another term' })).not.toBeInTheDocument()
  })

  it('publishes the list', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { ...LIST, is_published: true } })
    renderRoutes(routes, '/lists/l1')

    fireEvent.click(await screen.findByRole('button', { name: 'Publish' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/lists/l1/publish'))
  })

  it('only offers to delete empty sections', async () => {
    renderRoutes(routes, '/lists/l1')

    expect(await screen.findByRole('button', { name: 'Delete section Week 1' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete section Required' })).not.toBeInTheDocument()
    // Editors get drag handles (the read-only test checks they're absent otherwise)
    expect(screen.getByRole('button', { name: 'Reorder section Week 1' })).toBeInTheDocument()
  })

  it('adds a citation to a section', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: {} })
    renderRoutes(routes, '/lists/l1')

    const week1 = (await screen.findByRole('heading', { name: 'Week 1' })).closest('section')!
    fireEvent.click(within(week1).getByRole('button', { name: /Add citation/ }))

    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Enter details' }))
    fireEvent.change(within(dialog).getByLabelText(/^Title/), { target: { value: 'The Historian’s Craft' } })
    fireEvent.change(within(dialog).getByLabelText(/^Authors/), { target: { value: 'Bloch, Marc' } })
    fireEvent.change(within(dialog).getByLabelText(/^Year/), { target: { value: '1953' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add citation' }))

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        '/sections/s2/citations',
        expect.objectContaining({ title: 'The Historian’s Craft', author: ['Bloch, Marc'], year: 1953 })
      )
    )
  })

  it('shows field errors instead of saving an invalid citation', async () => {
    const post = vi.spyOn(apiClient, 'post')
    renderRoutes(routes, '/lists/l1')

    const week1 = (await screen.findByRole('heading', { name: 'Week 1' })).closest('section')!
    fireEvent.click(within(week1).getByRole('button', { name: /Add citation/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Enter details' }))
    fireEvent.change(within(dialog).getByLabelText(/^URL/), { target: { value: 'javascript:alert(1)' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add citation' }))

    expect(await within(dialog).findByText('Enter a title.')).toBeInTheDocument()
    expect(within(dialog).getByText(/must start with http/)).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
  })

  it('confirms before deleting a citation and shows server errors', async () => {
    const del = vi.spyOn(apiClient, 'delete').mockRejectedValue(
      Object.assign(new Error('fail'), { isAxiosError: true, response: { status: 404, data: { detail: 'Citation not found' } } })
    )
    renderRoutes(routes, '/lists/l1')

    fireEvent.click(await screen.findByRole('button', { name: 'Delete What Is History?' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Delete “What Is History\?”/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete citation' }))

    await waitFor(() => expect(del).toHaveBeenCalledWith('/citations/c1'))
    expect(await within(dialog).findByText('Citation not found')).toBeInTheDocument()
  })

  it('looks up an identifier and adds the library record with the instructor fields', async () => {
    const post = vi.spyOn(apiClient, 'post').mockImplementation(async (url: string) => {
      if (url === '/ingest/lookup') {
        return {
          data: {
            identifiers: [{ kind: 'isbn', value: '9780140449136' }],
            warnings: [],
            candidates: [
              {
                source_system: 'alma',
                source_identifier: '991234567890123',
                match_method: 'isbn',
                confidence: 0.95,
                authoritative: true,
                citation: { title: 'What is history?', author: ['Carr, E. H.'], editor: [], year: 1961, metadata: {} },
              },
            ],
          },
        }
      }
      return { data: {} }
    })
    renderRoutes(routes, '/lists/l1')

    const week1 = (await screen.findByRole('heading', { name: 'Week 1' })).closest('section')!
    fireEvent.click(within(week1).getByRole('button', { name: /Add citation/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText(/^Student note/), { target: { value: 'Chapter 1' } })
    const lookup = within(dialog).getByLabelText('DOI, ISBN or MMS ID')
    fireEvent.change(lookup, { target: { value: '978-0-14-044913-6' } })
    // Enter looks up rather than submitting the form
    fireEvent.keyDown(lookup, { key: 'Enter' })

    expect(await within(dialog).findByText('Your library')).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/ingest/lookup', { query: '978-0-14-044913-6' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add What is history?' }))

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/sections/s2/citations/from-source', {
        source_system: 'alma',
        source_identifier: '991234567890123',
        is_required: true,
        student_note: 'Chapter 1',
        staff_note: '',
      })
    )
    expect(post).not.toHaveBeenCalledWith('/sections/s2/citations', expect.anything())
  })

  it('keeps a bound citation read-only until it is unlinked', async () => {
    const bound = { ...LIST.sections[0].citations[0], is_bound: true, source_system: 'alma' }
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { ...LIST, sections: [{ ...LIST.sections[0], citations: [bound] }, LIST.sections[1]] },
    })
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { ...bound, is_bound: false } })
    renderRoutes(routes, '/lists/l1')

    expect(await screen.findByText('Library record')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Edit What Is History?' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText(/^Title/)).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText(/^Student note/), { target: { value: 'Skim' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save citation' }))

    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith('/citations/c1', { is_required: true, student_note: 'Skim', staff_note: '' })
    )

    fireEvent.click(screen.getByRole('button', { name: 'Edit What Is History?' }))
    const again = await screen.findByRole('dialog')
    fireEvent.click(within(again).getByRole('button', { name: /unlink it from the catalogue/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/citations/c1/unlink'))
    await waitFor(() => expect(within(again).getByLabelText(/^Title/)).toBeEnabled())
  })

  it('searches the library, shows availability, and adds a result', async () => {
    vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) =>
      url === '/ingest/capabilities' ? { data: { library_search: true } } : { data: LIST }
    )
    const post = vi.spyOn(apiClient, 'post').mockImplementation(async (url: string) => {
      if (url === '/ingest/search') {
        return {
          data: {
            total: 2,
            offset: 0,
            candidates: [
              {
                source_system: 'primo',
                source_identifier: 'cdi_crossref_primary_10_1016_x',
                match_method: 'search',
                confidence: 1,
                authoritative: false,
                availability: 'online',
                citation: {
                  title: 'Carbon pricing',
                  author: ['Zakeri, Atefe'],
                  editor: [],
                  year: 2015,
                  metadata: { journal_name: 'Energy policy' },
                },
              },
            ],
          },
        }
      }
      return { data: {} }
    })
    renderRoutes(routes, '/lists/l1')

    const week1 = (await screen.findByRole('heading', { name: 'Week 1' })).closest('section')!
    fireEvent.click(within(week1).getByRole('button', { name: /Add citation/ }))
    const dialog = await screen.findByRole('dialog')
    // Library search is the default when it's set up; results have their own Add buttons
    expect(await within(dialog).findByRole('tab', { name: 'Search the library', selected: true })).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'Add citation' })).not.toBeInTheDocument()

    const box = within(dialog).getByRole('textbox', { name: 'Search the library' })
    fireEvent.change(box, { target: { value: 'carbon pricing' } })
    fireEvent.keyDown(box, { key: 'Enter' })

    expect(await within(dialog).findByText('Online')).toBeInTheDocument()
    expect(within(dialog).getByText('Energy policy')).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/ingest/search', { query: 'carbon pricing', offset: 0, limit: 10 })
    fireEvent.click(within(dialog).getByLabelText('Required reading'))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add Carbon pricing' }))

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/sections/s2/citations/from-source', {
        source_system: 'primo',
        source_identifier: 'cdi_crossref_primary_10_1016_x',
        is_required: false,
        student_note: '',
        staff_note: '',
      })
    )
  })

  it('flags library records removed from the catalogue and shows what the sync changed', async () => {
    const gone = {
      ...LIST.sections[0].citations[0],
      is_bound: true,
      source_system: 'alma',
      source_status: 'missing',
      source_synced_at: '2026-11-20T07:15:00Z',
    }
    vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) => {
      if (url === '/citations/c1/history') {
        return {
          data: [
            { occurred_at: '2026-11-20T07:15:00Z', kind: 'missing', details: {} },
            { occurred_at: '2026-11-02T07:15:00Z', kind: 'updated', details: { title: ['a', 'b'], year: [1, 2] } },
          ],
        }
      }
      return { data: { ...LIST, sections: [{ ...LIST.sections[0], citations: [gone] }, LIST.sections[1]] } }
    })
    renderRoutes(routes, '/lists/l1')

    expect(await screen.findByText(/1 citation needs attention/)).toBeInTheDocument()
    expect(screen.getByText('Removed from catalogue')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Edit What Is History?' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/no longer in your library's catalogue/)).toBeInTheDocument()
    expect(within(dialog).getByText(/Last checked against the catalogue on/)).toBeInTheDocument()
    expect(await within(dialog).findByText(/Record removed from the catalogue/)).toBeInTheDocument()
    expect(within(dialog).getByText(/Updated from the catalogue: title, year/)).toBeInTheDocument()
  })

  it('is read-only for people who can only view the list', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { ...LIST, can_edit: false, can_publish: false } })
    renderRoutes(routes, '/lists/l1')

    expect(await screen.findByText('You can view this reading list but not change it.')).toBeInTheDocument()
    for (const name of ['Publish', 'Edit details', 'Import', /Add citation/, /Add section/, 'Edit What Is History?']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: /^Reorder/ })).not.toBeInTheDocument()
  })
})
