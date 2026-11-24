/** Editor entry point (index.html): authenticated SPA for instructors and librarians. */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider, createBrowserRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { createQueryClient } from '@/lib/queryClient'
import { editorRoutes } from '@/app/editorRoutes'
import '@/styles/fonts'
import '@/styles/theme.scss'

const queryClient = createQueryClient()
const router = createBrowserRouter(editorRoutes)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
    </QueryClientProvider>
  </StrictMode>
)
