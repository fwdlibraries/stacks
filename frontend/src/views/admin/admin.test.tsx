import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import AdminLayout from './AdminLayout'
import OrganizationView from './OrganizationView'
import ConnectionsView from './ConnectionsView'
import LinkResolutionView from './LinkResolutionView'
import LmsView from './LmsView'
import PeopleView from './PeopleView'
import { renderRoutes } from '@/test/renderWithProviders'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'

// Signed in: the current-user query only runs with a session
beforeEach(() => useAuthStore.setState({ token: 'session', refreshToken: 'r' }))
afterEach(() => {
  vi.restoreAllMocks()
  useAuthStore.setState({ token: null, refreshToken: null })
})

const ME = (manage: boolean, people = manage) => ({
  id: 'u1', email: 'a@uni.edu', display_name: 'Ada', is_system_admin: false, must_change_password: false,
  organization: { id: 'o1', name: 'Uni', slug: 'uni' },
  can: { manage_settings: manage, manage_people: people, manage_courses: manage, view_reports: manage },
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

const LMS = {
  tool: { login_url: 'https://s.uni.edu/lti/login', redirect_url: 'https://s.uni.edu/lti/launch',
          target_link_uri: 'https://s.uni.edu/lti/launch', jwks_url: 'https://s.uni.edu/lti/jwks' },
  platforms: [],
}

const PEOPLE = {
  total: 1, roles: ['Administrator', 'Librarian', 'Instructor', 'Viewer'], can_change_accounts: false,
  people: [{
    id: 'p1', display_name: 'Bob', email: 'bob@uni.edu', is_active: true, is_system_admin: false, from_lms: true,
    has_password: false, roles: [
      { id: 'a1', role: 'Viewer', scope: { type: 'college', id: 'c2', label: 'Science' }, can_remove: false },
      { id: 'a2', role: 'Instructor', scope: { type: 'course_offering', id: 'o1', label: 'HIST101 · fall-2026' }, can_remove: true },
    ],
  }],
}

const SCOPES = [
  { type: 'college', id: 'c1', label: 'Arts' },
  { type: 'department', id: 'd1', label: 'Arts › History' },
]

function mockGets(manage = true, people = manage) {
  return vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) => {
    const data: Record<string, unknown> = {
      '/auth/me': ME(manage, people), '/admin/organization': ORG, '/admin/sources': SOURCES, '/admin/link-resolution': LINKS,
      '/admin/lms': LMS, '/admin/people': PEOPLE, '/admin/scopes': SCOPES,
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
      { path: 'lms', element: <LmsView /> },
      { path: 'people', element: <PeopleView /> },
    ],
  },
]

describe('Administration', () => {
  it('is only for organization-wide administrators', async () => {
    mockGets(false)
    renderRoutes(routes, '/admin')
    expect(await screen.findByText(/You don't have access to administration/)).toBeInTheDocument()
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

  it('sends people-only admins (college, department) straight to People', async () => {
    mockGets(false, true)
    renderRoutes(routes, '/admin')
    expect(await screen.findByText('Bob')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/admin/people')
    expect(screen.queryByRole('link', { name: 'Library connections' })).not.toBeInTheDocument()
    expect(screen.queryByRole('switch', { name: 'Account on' })).not.toBeInTheDocument()
  })

  it('gives and removes roles only where allowed', async () => {
    mockGets(false, true)
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: {} })
    const del = vi.spyOn(apiClient, 'delete').mockResolvedValue({ data: null })
    renderRoutes(routes, '/admin/people')

    expect(await screen.findByText('Bob')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remove Viewer for Science/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Remove Instructor for HIST101 · fall-2026 from Bob' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/admin/people/p1/roles/a2'))

    fireEvent.click(screen.getByRole('button', { name: 'Add role' }))
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'Librarian' } })
    fireEvent.change(screen.getByLabelText('Where'), { target: { value: 'department:d1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/admin/people/p1/roles', { role: 'Librarian', scope_type: 'department', scope_id: 'd1' })
    )
  })

  it('shows the tool URLs to copy and registers an LMS', async () => {
    mockGets()
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: LMS })
    renderRoutes(routes, '/admin/lms')

    expect(await screen.findByDisplayValue('https://s.uni.edu/lti/jwks')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Register an LMS' }))
    const values: Record<string, string> = {
      Issuer: 'https://uni.brightspace.com', 'Client ID': 'abc',
      'OpenID Connect authentication endpoint': 'https://uni.brightspace.com/d2l/lti/authenticate',
      'OAuth2 access token URL': 'https://auth.brightspace.com/core/connect/token',
      'LMS keyset URL': 'https://uni.brightspace.com/d2l/.well-known/jwks', 'Deployment IDs': 'dep-1 dep-2',
    }
    for (const [label, value] of Object.entries(values)) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    fireEvent.click(screen.getByRole('button', { name: 'Register' }))
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/admin/lms', {
        issuer: 'https://uni.brightspace.com', client_id: 'abc',
        auth_login_url: 'https://uni.brightspace.com/d2l/lti/authenticate',
        auth_token_url: 'https://auth.brightspace.com/core/connect/token',
        jwks_url: 'https://uni.brightspace.com/d2l/.well-known/jwks', deployment_ids: ['dep-1', 'dep-2'],
      })
    )
  })
})
