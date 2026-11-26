import { Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { Alert, Nav, Spinner } from "react-bootstrap";
import { useCurrentUser } from "@/api/hooks/useAuth";

/** Administration. Settings need settings.manage organization-wide; People and Reports need
 * people.manage / reports.view anywhere (and show only what's in the user's scope). */
export default function AdminLayout() {
  const { data: user, isLoading } = useCurrentUser();
  const location = useLocation();

  if (isLoading) {
    return (
      <Spinner animation="border" role="status">
        <span className="visually-hidden">Loading…</span>
      </Spinner>
    );
  }
  const settings = Boolean(user?.can?.manage_settings);
  const people = Boolean(user?.can?.manage_people);
  const reports = Boolean(user?.can?.view_reports);
  if (!settings && !people && !reports) {
    return (
      <Alert variant="warning">You don't have access to administration.</Alert>
    );
  }
  // Send people to the first tab they can use (e.g. department admins: People)
  const path = location.pathname.replace(/\/$/, "");
  const allowed = (
    settings
      ? [
          "/admin",
          "/admin/look",
          "/admin/signin",
          "/admin/connections",
          "/admin/links",
          "/admin/lms",
        ]
      : []
  )
    .concat(people ? ["/admin/people"] : [])
    .concat(reports ? ["/admin/reports"] : []);
  if (!allowed.includes(path)) {
    return <Navigate to={allowed[0]} replace />;
  }

  return (
    <div style={{ maxWidth: "980px" }}>
      <h1 className="mb-3">Administration</h1>
      <Nav variant="tabs" className="mb-4" as="nav" aria-label="Administration">
        {settings && (
          <>
            <Nav.Link as={NavLink} to="/admin" end>
              Organization
            </Nav.Link>
            <Nav.Link as={NavLink} to="/admin/look">
              Look and feel
            </Nav.Link>
            <Nav.Link as={NavLink} to="/admin/signin">
              Sign-in
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
        {reports && (
          <Nav.Link as={NavLink} to="/admin/reports">
            Reports
          </Nav.Link>
        )}
      </Nav>
      <Outlet />
    </div>
  );
}
