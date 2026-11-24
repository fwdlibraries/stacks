/** Public entry point (public.html): unauthenticated student reading list view. */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider, createBrowserRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/lib/queryClient'
import { publicRoutes } from '@/app/publicRoutes'
import '@/styles/fonts'
import '@/styles/theme.scss'

const queryClient = createQueryClient()
const router = createBrowserRouter(publicRoutes)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>
)
