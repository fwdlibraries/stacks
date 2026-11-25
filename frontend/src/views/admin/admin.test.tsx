import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import AdminLayout from './AdminLayout'
import OrganizationView from './OrganizationView'
import ConnectionsView from './ConnectionsView'
import LinkResolutionView from './LinkResolutionView'
import { renderRoutes } from '@/test/renderWithProviders'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'

// Signed in: the current-user query only runs with a session
beforeEach(() => useAuthStore.setState({ token: 'session', refreshToken: 'r' }))
afterEach(() => {
  vi.restoreAllMocks()
  useAuthStore.setState({ token: null, refreshToken: null })
})

const ME = (manage: boolean) => ({
  id: 'u1', email: 'a@uni.edu', display_name: 'Ada', is_system_admin: false, must_change_password: false,
  organization: { id: 'o1', name: 'Uni', slug: 'uni' },
  can: { manage_settings: manage, manage_people: manage, manage_courses: manage, view_reports: manage },
})

const ORG = {
  id: 'o1', name: 'Uni', slug: 'uni', address: 'https://stacks.uni.edu',
  domains: [{ id: 'd1', hostname: 'stacks.uni.edu', is_primary: true }],
  lms_origins: null, default_lms_origins: ['https://default.example'],
  contact_email: null, default_contact_email: null, can_manage_domains: false,
}

const SOURCES = [
  { kind: 'alma', configured: true, is_active: true, config: { region: 'na' }, key_set: true, updated_at: '2026-11-01' },
  { kind: 'primo', configured: false, is_active: false, config: {}, key_set: false },
  { kind: 'libkey', configured: false, is_active: false, config: {}, key_set: false },
]

const LINKS = {
  stack: ['libkey', 'alma', 'open_access'], cache_ttl_seconds: 21600, step_timeout_seconds: 2.5,
  available: { libkey: false, alma: true, open_access: true },
}

function mockGets(manage = true) {
  return vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) => {
    const data: Record<string, unknown> = {
      '/auth/me': ME(manage), '/admin/organization': ORG, '/admin/sources': SOURCES, '/admin/link-resolution': LINKS,
    }
    return { data: data[url] }
  })
}

const routes = [
  {
    path: '/admin',
    element: <AdminLayout />,
    children: [
      { index: true, element: <OrganizationView /> },
      { path: 'connections', element: <ConnectionsView /> },
      { path: 'links', element: <LinkResolutionView /> },
    ],
  },
]

describe('Administration', () => {
  it('is only for organization-wide administrators', async () => {
    mockGets(false)
    renderRoutes(routes, '/admin')
    expect(await screen.findByText(/Only administrators for the whole organization/)).toBeInTheDocument()
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
  })

  it('saves organization settings; domains are read-only for organization admins', async () => {
    mockGets()
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: ORG })
    renderRoutes(routes, '/admin')

    expect(await screen.findByText('https://stacks.uni.edu')).toBeInTheDocument()
    expect(screen.getByText(/Your Stacks provider manages these addresses/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remove stacks/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText(/Use this installation's default/))
    fireEvent.change(screen.getByLabelText('LMS sites, one per line'), {
      target: { value: 'https://uni.brightspace.com\nhttps://uni.instructure.com' },
    })
    fireEvent.change(screen.getByLabelText(/Contact address/), { target: { value: 'lib@uni.edu' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith('/admin/organization', {
        name: 'Uni',
        lms_origins: ['https://uni.brightspace.com', 'https://uni.instructure.com'],
        contact_email: 'lib@uni.edu',
      })
    )
  })

  it('tests and saves a connection without ever showing the key', async () => {
    mockGets()
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { ok: true, message: 'Connected for 01UNI' } })
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: SOURCES[0] })
    renderRoutes(routes, '/admin/connections')

    const alma = (await screen.findByRole('heading', { name: /Alma/ })).closest('.card') as HTMLElement
    const key = within(alma).getByLabelText(/API key/)
    expect(key).toHaveAttribute('type', 'password')
    expect(key).toHaveAttribute('placeholder', 'Saved (leave blank to keep)')

    fireEvent.click(within(alma).getByRole('button', { name: 'Test connection' }))
    expect(await within(alma).findByText('Connected for 01UNI')).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/admin/sources/alma/test', { config: { region: 'na' }, api_key: undefined })

    fireEvent.click(within(alma).getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith('/admin/sources/alma', { config: { region: 'na' }, api_key: undefined, is_active: true })
    )

    // Removing asks first
    const del = vi.spyOn(apiClient, 'delete').mockResolvedValue({ data: null })
    fireEvent.click(within(alma).getByRole('button', { name: 'Remove' }))
    expect(within(alma).getByText(/Remove the Alma connection and its key\?/)).toBeInTheDocument()
    expect(del).not.toHaveBeenCalled()

    // A new connection can't be tested without a key
    const libkey = screen.getByRole('heading', { name: /LibKey/ }).closest('.card') as HTMLElement
    expect(within(libkey).getByRole('button', { name: 'Test connection' })).toBeDisabled()
  })

  it('reorders and switches resolver steps, and tries an identifier', async () => {
    mockGets()
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: LINKS })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { url: 'https://alma/sd', resolved_by: 'alma', detail: 'ScienceDirect', retracted: false,
              steps: [{ step: 'libkey', outcome: 'skipped' }, { step: 'alma', outcome: 'found', detail: 'ScienceDirect' }] },
    })
    renderRoutes(routes, '/admin/links')

    expect(await screen.findByText('Not set up')).toBeInTheDocument() // LibKey
    fireEvent.click(screen.getByRole('button', { name: 'Move Open access up' }))
    fireEvent.click(screen.getByLabelText('Use LibKey'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith('/admin/link-resolution', {
        stack: ['open_access', 'alma'], cache_ttl_seconds: 21600, step_timeout_seconds: 2.5,
      })
    )

    fireEvent.change(screen.getByLabelText('DOI, ISBN or MMS ID to try'), { target: { value: '10.1016/x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Try' }))
    expect(await screen.findByText(/Students go straight to ScienceDirect/)).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/admin/link-resolution/try', { query: '10.1016/x' })
  })
})
