import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { editorRoutes } from './editorRoutes'
import { renderRoutes } from '@/test/renderWithProviders'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'

describe('editor routes', () => {
  it('redirects unauthenticated users to the sign-in page', async () => {
    useAuthStore.setState({ token: null })
    renderRoutes(editorRoutes, '/lists')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/login')
  })

  it('shows the reading lists page when signed in', async () => {
    useAuthStore.setState({ token: 'test-token' })
    vi.spyOn(apiClient, 'get').mockResolvedValueOnce({ data: [] })
    renderRoutes(editorRoutes, '/')

    expect(await screen.findByRole('heading', { name: 'Reading lists' })).toBeInTheDocument()
    expect(await screen.findByText('No reading lists yet')).toBeInTheDocument()
  })

  it('renders a not-found page for unknown URLs', async () => {
    renderRoutes(editorRoutes, '/nowhere')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
