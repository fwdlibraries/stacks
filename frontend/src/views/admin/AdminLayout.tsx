import { Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { Alert, Nav, Spinner } from "react-bootstrap";
import { useCurrentUser } from "@/api/hooks/useAuth";

type Need = "settings" | "courses" | "people" | "reports";

/** The sidebar, in order. Each page needs one permission. */
const SECTIONS: { group: string; need: Need; pages: { to: string; label: string }[] }[] = [
  {
    group: "Settings",
    need: "settings",
    pages: [
      { to: "/admin", label: "Organization" },
      { to: "/admin/look", label: "Look and feel" },
      { to: "/admin/signin", label: "Sign-in" },
      { to: "/admin/terms", label: "Terms" },
      { to: "/admin/connections", label: "Library connections" },
      { to: "/admin/links", label: "Link resolution" },
      { to: "/admin/lms", label: "LMS" },
    ],
  },
  { group: "Courses", need: "courses", pages: [{ to: "/admin/rollover", label: "Rollover" }] },
  { group: "People", need: "people", pages: [{ to: "/admin/people", label: "People" }] },
  { group: "Insights", need: "reports", pages: [{ to: "/admin/reports", label: "Reports" }] },
];

/** Administration. Settings need settings.manage organization-wide; People and Reports need
 * people.manage / reports.view anywhere (and show only what's in the user's scope). */
export default function AdminLayout() {
  const { data: user, isLoading } = useCurrentUser();
  const location = useLocation();

  if (isLoading) {
    return (
      <Spinner animation="border" role="status" className="m-4">
        <span className="visually-hidden">Loading…</span>
      </Spinner>
    );
  }
  const can: Record<Need, boolean> = {
    settings: Boolean(user?.can?.manage_settings),
    courses: Boolean(user?.can?.manage_courses),
    people: Boolean(user?.can?.manage_people),
    reports: Boolean(user?.can?.view_reports),
  };
  const sections = SECTIONS.filter((s) => can[s.need]);
  if (sections.length === 0) {
    return (
      <div className="p-4">
        <Alert variant="warning">You don't have access to administration.</Alert>
      </div>
    );
  }
  // Send people to the first page they can use (e.g. department admins: People)
  const path = location.pathname.replace(/\/$/, "");
  const pages = sections.flatMap((s) => s.pages);
  const current = pages.find((p) => p.to === path);
  if (!current) {
    return <Navigate to={pages[0].to} replace />;
  }

  return (
    <div className="d-flex flex-wrap flex-lg-nowrap flex-grow-1">
      <aside className="stacks-sidenav px-3 py-4">
        <Nav as="nav" aria-label="Administration" className="flex-column">
          {sections.map((s) => (
            <div key={s.group}>
              <div className="stacks-sidenav-group text-caps">{s.group}</div>
              {s.pages.map((p) => (
                <Nav.Link key={p.to} as={NavLink} to={p.to} end>
                  {p.label}
                </Nav.Link>
              ))}
            </div>
          ))}
        </Nav>
      </aside>
      <div className="stacks-admin-main px-3 px-md-4 py-4">
        <div style={{ maxWidth: "1120px" }}>
          <div className="small text-body-secondary mb-1">Administration</div>
          <h1 className="mb-3">{current.label}</h1>
          <Outlet />
        </div>
      </div>
    </div>
  );
}
