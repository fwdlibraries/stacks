import { NavLink, Outlet } from 'react-router-dom'
import { Alert, Nav, Spinner } from 'react-bootstrap'
import { useCurrentUser } from '@/api/hooks/useAuth'

/** Administration: organization-wide settings. Needs settings.manage for the whole organization. */
export default function AdminLayout() {
  const { data: user, isLoading } = useCurrentUser()

  if (isLoading) {
    return (
      <Spinner animation="border" role="status">
        <span className="visually-hidden">Loading…</span>
      </Spinner>
    )
  }
  if (!user?.can?.manage_settings) {
    return <Alert variant="warning">Only administrators for the whole organization can change these settings.</Alert>
  }

  return (
    <div style={{ maxWidth: '860px' }}>
      <h1 className="mb-3">Administration</h1>
      <Nav variant="tabs" className="mb-4" as="nav" aria-label="Administration">
        <Nav.Link as={NavLink} to="/admin" end>
          Organization
        </Nav.Link>
        <Nav.Link as={NavLink} to="/admin/connections">
          Library connections
        </Nav.Link>
        <Nav.Link as={NavLink} to="/admin/links">
          Link resolution
        </Nav.Link>
      </Nav>
      <Outlet />
    </div>
  )
}
