import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button, Container, Nav, Navbar } from 'react-bootstrap'
import { SignOut } from '@phosphor-icons/react'
import { useLogout } from '@/api/hooks/useAuth'

/** Authenticated editor layout: top navbar + routed content. */
export function AppShell() {
  const navigate = useNavigate()
  const logout = useLogout()

  const handleSignOut = () => {
    logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })
  }

  return (
    <>
      <Navbar bg="white" expand="md" className="border-bottom">
        <Container>
          <Navbar.Brand as={Link} to="/lists" className="d-flex align-items-center gap-2">
            <img src="/favicon.svg" alt="" width={32} height={32} />
            <span className="stacks-wordmark">Stacks</span>
          </Navbar.Brand>
          <Navbar.Toggle aria-controls="stacks-nav" />
          <Navbar.Collapse id="stacks-nav">
            <Nav className="me-auto">
              <Nav.Link as={NavLink} to="/lists">
                Reading lists
              </Nav.Link>
            </Nav>
            <Button
              variant="outline-secondary"
              size="sm"
              onClick={handleSignOut}
              disabled={logout.isPending}
              className="d-inline-flex align-items-center gap-1"
            >
              <SignOut aria-hidden="true" />
              Sign out
            </Button>
          </Navbar.Collapse>
        </Container>
      </Navbar>

      <main>
        <Container className="py-4">
          <Outlet />
        </Container>
      </main>
    </>
  )
}

export default AppShell
