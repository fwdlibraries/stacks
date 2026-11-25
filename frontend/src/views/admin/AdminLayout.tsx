import { Navigate, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Alert, Nav, Spinner } from 'react-bootstrap'
import { useCurrentUser } from '@/api/hooks/useAuth'

/** Administration. Settings need settings.manage organization-wide; People needs people.manage anywhere. */
export default function AdminLayout() {
  const { data: user, isLoading } = useCurrentUser()
  const location = useLocation()

  if (isLoading) {
    return (
      <Spinner animation="border" role="status">
        <span className="visually-hidden">Loading…</span>
      </Spinner>
    )
  }
  const settings = Boolean(user?.can?.manage_settings)
  const people = Boolean(user?.can?.manage_people)
  if (!settings && !people) {
    return <Alert variant="warning">You don't have access to administration.</Alert>
  }
  // College and department admins manage people only
  if (!settings && location.pathname.replace(/\/$/, '') !== '/admin/people') {
    return <Navigate to="/admin/people" replace />
  }

  return (
    <div style={{ maxWidth: '860px' }}>
      <h1 className="mb-3">Administration</h1>
      <Nav variant="tabs" className="mb-4" as="nav" aria-label="Administration">
        {settings && (
          <>
            <Nav.Link as={NavLink} to="/admin" end>
              Organization
            </Nav.Link>
            <Nav.Link as={NavLink} to="/admin/connections">
              Library connections
            </Nav.Link>
            <Nav.Link as={NavLink} to="/admin/links">
              Link resolution
            </Nav.Link>
            <Nav.Link as={NavLink} to="/admin/lms">
              LMS
            </Nav.Link>
          </>
        )}
        {people && (
          <Nav.Link as={NavLink} to="/admin/people">
            People
          </Nav.Link>
        )}
      </Nav>
      <Outlet />
    </div>
  )
}
