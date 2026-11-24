import type { RouteObject } from 'react-router-dom'
import PublicListView from '@/views/public/PublicListView'
import NotFoundView from '@/views/errors/NotFoundView'

/**
 * Routes for the lightweight student entry (public.html). Keep imports here
 * minimal: nothing from the editor (auth, websockets, dnd-kit) belongs in this bundle.
 */
export const publicRoutes: RouteObject[] = [
  { path: '/public/:orgSlug/:courseCode/:term', element: <PublicListView /> },
  { path: '*', element: <NotFoundView /> },
]
