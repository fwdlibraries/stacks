import { Link, Navigate, type RouteObject } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { RequireAuth } from '@/components/layout/RequireAuth'
import LoginView from '@/views/auth/LoginView'
import LaunchView from '@/views/auth/LaunchView'
import ListsIndexView from '@/views/lists/ListsIndexView'
import ListEditorView from '@/views/lists/ListEditorView'
import NotFoundView from '@/views/errors/NotFoundView'
import ConnectExtensionView from '@/views/extension/ConnectExtensionView'
import AdminLayout from '@/views/admin/AdminLayout'
import OrganizationView from '@/views/admin/OrganizationView'
import ConnectionsView from '@/views/admin/ConnectionsView'
import LinkResolutionView from '@/views/admin/LinkResolutionView'
import LmsView from '@/views/admin/LmsView'
import PeopleView from '@/views/admin/PeopleView'
import ReportsView from '@/views/admin/ReportsView'

/** Routes for the editor SPA (index.html). Student URLs under /public/ use public.html. */
export const editorRoutes: RouteObject[] = [
  { path: '/login', element: <LoginView /> },
  // LTI launch landing page: exchanges a one-time code for tokens
  { path: '/launch', element: <LaunchView /> },
  {
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/lists" replace /> },
      { path: 'lists', element: <ListsIndexView /> },
      { path: 'lists/:listId', element: <ListEditorView /> },
      { path: 'extension/connect', element: <ConnectExtensionView /> },
      {
        path: 'admin',
        element: <AdminLayout />,
        children: [
          { index: true, element: <OrganizationView /> },
          { path: 'connections', element: <ConnectionsView /> },
          { path: 'links', element: <LinkResolutionView /> },
          { path: 'lms', element: <LmsView /> },
          { path: 'people', element: <PeopleView /> },
          { path: 'reports', element: <ReportsView /> },
        ],
      },
    ],
  },
  {
    path: '*',
    element: <NotFoundView action={<Link to="/lists" className="btn btn-primary">Go to reading lists</Link>} />,
  },
]
