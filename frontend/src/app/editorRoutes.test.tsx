import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { editorRoutes } from './editorRoutes'
import { renderRoutes } from '@/test/renderWithProviders'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'

const ME = {
  id: 'u1',
  email: 'librarian@example.edu',
  display_name: 'Test Librarian',
  is_system_admin: false,
  must_change_password: false,
  organization: { id: 'o1', name: 'Demo University', slug: 'demo' },
}

/** Answer GETs by URL so tests don't depend on request order */
function mockGets(routes: Record<string, unknown>) {
  return vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) => {
    if (url in routes) return { data: routes[url] }
    throw new Error(`Unexpected GET ${url}`)
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  useAuthStore.getState().clear()
})

describe('editor routes', () => {
  it('redirects unauthenticated users to the sign-in page', async () => {
    renderRoutes(editorRoutes, '/lists')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/login')
  })

  it('signs in with email and password, then shows reading lists', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { access_token: 'a', refresh_token: 'r', token_type: 'bearer', expires_in: 3600 },
    })
    mockGets({ '/lists': [], '/auth/me': ME })
    renderRoutes(editorRoutes, '/login')

    fireEvent.change(await screen.findByLabelText(/Email/), { target: { value: 'librarian@example.edu' } })
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'correct horse' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'Reading lists' })).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/auth/local/login', {
      email: 'librarian@example.edu',
      password: 'correct horse',
    })
    expect(useAuthStore.getState()).toMatchObject({ token: 'a', status: 'signed_in' })
    expect(await screen.findByText(/Test Librarian · Demo University/)).toBeInTheDocument()
  })

  it('shows the reading lists page when signed in', async () => {
    useAuthStore.getState().setTokens({ access_token: 'a', refresh_token: 'r' })
    mockGets({ '/lists': [], '/auth/me': ME })
    renderRoutes(editorRoutes, '/')

    expect(await screen.findByRole('heading', { name: 'Reading lists' })).toBeInTheDocument()
    expect(await screen.findByText('No reading lists yet')).toBeInTheDocument()
  })

  it('renders a not-found page for unknown URLs', async () => {
    renderRoutes(editorRoutes, '/nowhere')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
