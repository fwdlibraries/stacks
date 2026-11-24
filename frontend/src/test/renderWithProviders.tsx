import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation, useRoutes, type RouteObject } from 'react-router-dom'

/**
 * Render a route table at the given URL with a fresh, non-retrying QueryClient.
 *
 * Uses MemoryRouter + useRoutes rather than createMemoryRouter: the data router
 * builds a Node `Request` on navigation, which rejects jsdom's AbortSignal.
 * The current pathname is exposed via `data-testid="location"`.
 */
export function renderRoutes(routes: RouteObject[], url: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]}>
        <RouteTable routes={routes} />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function RouteTable({ routes }: { routes: RouteObject[] }) {
  const location = useLocation()
  return (
    <>
      {useRoutes(routes)}
      <output data-testid="location" hidden>
        {location.pathname}
      </output>
    </>
  )
}
