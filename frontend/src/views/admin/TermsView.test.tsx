import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import TermsView from './TermsView'
import { renderRoutes } from '@/test/renderWithProviders'
import apiClient from '@/api/client'

const SETTINGS = {
  section_code_pattern: '{crn}.{term}',
  terms: [
    { id: 't1', code: '202710', name: 'Fall 2027', starts_on: '2027-08-30', ends_on: '2027-12-17',
      rollover_on: '2027-07-01', lists_due_on: '2027-08-01', offerings: 3 },
    { id: 't2', code: 'spring-2028', name: 'Spring 2028', starts_on: null, ends_on: null,
      rollover_on: null, lists_due_on: null, offerings: 0 },
  ],
}

const routes = [{ path: '/admin/terms', element: <TermsView /> }]

afterEach(() => vi.restoreAllMocks())

describe('TermsView', () => {
  it('lists terms; only unused ones can be removed', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: SETTINGS })
    renderRoutes(routes, '/admin/terms')

    expect(await screen.findByText('Fall 2027')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove Fall 2027' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove Spring 2028' })).toBeInTheDocument()
  })

  it('keeps the code of a term courses use', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: SETTINGS })
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: SETTINGS })
    renderRoutes(routes, '/admin/terms')

    fireEvent.click(await screen.findByRole('button', { name: 'Edit Fall 2027' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText(/^Code/)).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText(/^Name/), { target: { value: 'Fall ’27' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save term' }))

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith('/admin/terms/t1', {
        code: '202710', name: 'Fall ’27', starts_on: '2027-08-30', ends_on: '2027-12-17',
        rollover_on: '2027-07-01', lists_due_on: '2027-08-01',
      })
    )
  })

  it('tries a course code against the pattern', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: SETTINGS })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { matches: true, error: null, term: '202710', term_name: 'Fall 2027', crn: '40112', section: null, course: null },
    })
    renderRoutes(routes, '/admin/terms')

    fireEvent.change(await screen.findByLabelText('Try a course code'), { target: { value: '40112.202710' } })
    fireEvent.click(screen.getByRole('button', { name: 'Try' }))

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/admin/terms-pattern/try', { section_code_pattern: '{crn}.{term}', code: '40112.202710' })
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Term 202710 (Fall 2027) · CRN 40112')
  })
})
