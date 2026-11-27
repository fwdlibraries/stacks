import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import LaunchView from './LaunchView'
import { renderRoutes } from '@/test/renderWithProviders'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const routes = [
  { path: '/launch', element: <LaunchView /> },
  { path: '/lists/:id', element: <p>List page</p> },
  { path: '/lists', element: <p>Lists index</p> },
]

afterEach(() => {
  vi.restoreAllMocks()
  useAuthStore.getState().clear()
})

describe('LaunchView', () => {
  it('exchanges the code once, stores tokens and opens the list', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { access_token: 'a', refresh_token: 'r', next: '/lists/l1' },
    })
    renderRoutes(routes, '/launch?code=abc')

    expect(await screen.findByText('List page')).toBeInTheDocument()
    expect(post).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenCalledWith('/auth/lti/exchange', { code: 'abc' })
    expect(useAuthStore.getState()).toMatchObject({ token: 'a', status: 'signed_in' })
    expect(screen.getByTestId('location')).toHaveTextContent('/lists/l1')
  })

  it('refuses to follow an off-site next path', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { access_token: 'a', refresh_token: 'r', next: '//evil.example/phish' },
    })
    renderRoutes(routes, '/launch?code=abc')

    expect(await screen.findByText('Lists index')).toBeInTheDocument()
  })

  it('explains an expired code', async () => {
    vi.spyOn(apiClient, 'post').mockRejectedValue(
      Object.assign(new Error('401'), {
        isAxiosError: true,
        response: { status: 401, data: { detail: 'This sign-in link has expired. Open Stacks again from your course.' } },
      })
    )
    renderRoutes(routes, '/launch?code=used')

    expect(await screen.findByText(/sign-in link has expired/)).toBeInTheDocument()
    expect(useAuthStore.getState().token).toBeNull()
  })

  it('handles a missing code without calling the API', async () => {
    const post = vi.spyOn(apiClient, 'post')
    renderRoutes(routes, '/launch')

    expect(await screen.findByText(/link is incomplete/)).toBeInTheDocument()
    await waitFor(() => expect(post).not.toHaveBeenCalled())
  })
})
