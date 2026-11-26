import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  CloseButton,
  Form,
  InputGroup,
  ListGroup,
  Spinner,
} from "react-bootstrap";
import {
  PEOPLE_PAGE_SIZE,
  useAssignableScopes,
  useGiveRole,
  useInvite,
  usePeople,
  useSetAccountActive,
  useTakeRole,
  type Person,
  type Scope,
} from "@/api/hooks/useAdmin";
import { apiErrorMessage } from "@/lib/apiError";

const SCOPE_GROUPS: [Scope["type"], string][] = [
  ["organization", "Organization"],
  ["college", "Colleges"],
  ["department", "Departments"],
  ["course_template", "Courses"],
];

export default function PeopleView() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const people = usePeople(query, offset);
  const scopes = useAssignableScopes();
  const page = people.data;

  return (
    <>
      <p className="text-body-secondary">
        People appear here once they’ve opened Stacks from your LMS (they’re
        then Instructor of that course), or after your Stacks administrator adds
        them. Give roles for the whole organization, a college, a department or
        a course.
      </p>
      <InviteCard roles={page?.roles ?? []} scopes={scopes.data ?? []} />
      <Form
        className="mb-3"
        style={{ maxWidth: "28rem" }}
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setQuery(search.trim());
        }}
      >
        <InputGroup>
          <Form.Control
            aria-label="Search people"
            placeholder="Name or email"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Button type="submit" variant="outline-primary">
            Search
          </Button>
        </InputGroup>
      </Form>

      {people.isLoading && (
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading…</span>
        </Spinner>
      )}
      {people.isError && (
        <Alert variant="danger">
          {apiErrorMessage(people.error, "People could not be loaded.")}
        </Alert>
      )}
      {page && (
        <>
          <p className="small text-body-secondary" aria-live="polite">
            {page.total} {page.total === 1 ? "person" : "people"}
          </p>
          <ListGroup className="mb-3">
            {page.people.map((p) => (
              <PersonRow
                key={p.id}
                person={p}
                roles={page.roles}
                scopes={scopes.data ?? []}
                canChangeAccounts={page.can_change_accounts}
              />
            ))}
          </ListGroup>
          {page.total > PEOPLE_PAGE_SIZE && (
            <div className="d-flex gap-2">
              <Button
                size="sm"
                variant="outline-secondary"
                disabled={offset === 0}
                onClick={() =>
                  setOffset(Math.max(0, offset - PEOPLE_PAGE_SIZE))
                }
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="outline-secondary"
                disabled={offset + PEOPLE_PAGE_SIZE >= page.total}
                onClick={() => setOffset(offset + PEOPLE_PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}

function PersonRow({
  person,
  roles,
  scopes,
  canChangeAccounts,
}: {
  person: Person;
  roles: string[];
  scopes: Scope[];
  canChangeAccounts: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const [role, setRole] = useState(roles[1] ?? roles[0]);
  const [scopeKey, setScopeKey] = useState("");
  const give = useGiveRole();
  const take = useTakeRole();
  const active = useSetAccountActive();
  const error = give.error || take.error || active.error;

  const add = () => {
    const scope = scopes.find((s) => `${s.type}:${s.id}` === scopeKey);
    if (!scope) return;
    give.mutate(
      { userId: person.id, role, scope_type: scope.type, scope_id: scope.id },
      { onSuccess: () => setAdding(false) },
    );
  };

  return (
    <ListGroup.Item
      className={person.is_active ? undefined : "bg-body-tertiary"}
    >
      <div className="d-flex justify-content-between align-items-start gap-2">
        <div>
          <div className="fw-semibold">
            {person.display_name}{" "}
            {person.is_system_admin && <Badge bg="dark">System admin</Badge>}{" "}
            {person.from_lms && (
              <Badge bg="light" text="dark">
                From LMS
              </Badge>
            )}{" "}
            {person.invited && <Badge bg="info">Invited</Badge>}{" "}
            {!person.is_active && <Badge bg="secondary">Off</Badge>}
          </div>
          <div className="small text-body-secondary">{person.email}</div>
        </div>
        {canChangeAccounts && (
          <Form.Check
            type="switch"
            id={`active-${person.id}`}
            label="Account on"
            checked={person.is_active}
            onChange={(e) =>
              active.mutate({ userId: person.id, is_active: e.target.checked })
            }
          />
        )}
      </div>

      <div
        className="d-flex flex-wrap gap-2 mt-2"
        aria-label={`${person.display_name}'s roles`}
      >
        {person.roles.length === 0 && (
          <span className="small text-body-secondary">No roles</span>
        )}
        {person.roles.map((r) => (
          <Badge
            key={r.id}
            bg="light"
            text="dark"
            className="d-inline-flex align-items-center gap-1 border fw-normal"
          >
            <strong>{r.role}</strong> · {r.scope.label}
            {r.can_remove && (
              <CloseButton
                style={{ fontSize: "0.6rem" }}
                aria-label={`Remove ${r.role} for ${r.scope.label} from ${person.display_name}`}
                onClick={() => take.mutate({ userId: person.id, id: r.id })}
              />
            )}
          </Badge>
        ))}
        {!adding && scopes.length > 0 && (
          <Button
            size="sm"
            variant="link"
            className="p-0"
            onClick={() => setAdding(true)}
          >
            Add role
          </Button>
        )}
      </div>

      {adding && (
        <div className="d-flex flex-wrap gap-2 mt-2 align-items-center">
          <Form.Select
            size="sm"
            style={{ width: "auto" }}
            aria-label="Role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            {roles.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Form.Select>
          <span className="small">for</span>
          <Form.Select
            size="sm"
            style={{ width: "auto" }}
            aria-label="Where"
            value={scopeKey}
            onChange={(e) => setScopeKey(e.target.value)}
          >
            <option value="">Choose where…</option>
            {SCOPE_GROUPS.map(([type, label]) => {
              const options = scopes.filter((s) => s.type === type);
              return options.length ? (
                <optgroup key={type} label={label}>
                  {options.map((s) => (
                    <option key={s.id} value={`${s.type}:${s.id}`}>
                      {s.label}
                    </option>
                  ))}
                </optgroup>
              ) : null;
            })}
          </Form.Select>
          <Button
            size="sm"
            onClick={add}
            disabled={!scopeKey || give.isPending}
          >
            Add
          </Button>
          <Button
            size="sm"
            variant="outline-secondary"
            onClick={() => setAdding(false)}
          >
            Cancel
          </Button>
        </div>
      )}
      {error && (
        <Alert variant="danger" className="small mt-2 mb-0">
          {apiErrorMessage(error, "That didn’t work.")}
        </Alert>
      )}
    </ListGroup.Item>
  );
}

function InviteCard({ roles, scopes }: { roles: string[]; scopes: Scope[] }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("Librarian");
  const [scopeKey, setScopeKey] = useState("");
  const invite = useInvite();
  if (!open) {
    return (
      <Button
        variant="outline-primary"
        size="sm"
        className="mb-3"
        onClick={() => setOpen(true)}
        disabled={scopes.length === 0}
      >
        Invite someone
      </Button>
    );
  }
  const submit = () => {
    const scope = scopes.find((s) => `${s.type}:${s.id}` === scopeKey);
    if (!scope) return;
    invite.mutate(
      {
        email: email.trim(),
        display_name: name.trim(),
        role,
        scope_type: scope.type,
        scope_id: scope.id,
      },
      {
        onSuccess: () => {
          setOpen(false);
          setEmail("");
          setName("");
        },
      },
    );
  };
  return (
    <div className="border rounded p-3 mb-3">
      <h2 className="h6">Invite someone</h2>
      <p className="small text-body-secondary">
        They sign in with your institution’s account (Administration → Sign-in);
        their first sign-in with this email links to the invitation.
      </p>
      <div className="d-flex flex-wrap gap-2 align-items-center">
        <Form.Control
          size="sm"
          style={{ maxWidth: "14rem" }}
          aria-label="Email"
          placeholder="name@csp.edu"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Form.Control
          size="sm"
          style={{ maxWidth: "12rem" }}
          aria-label="Name"
          placeholder="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Form.Select
          size="sm"
          style={{ width: "auto" }}
          aria-label="Invite as"
          value={role}
          onChange={(e) => setRole(e.target.value)}
        >
          {roles.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </Form.Select>
        <span className="small">for</span>
        <Form.Select
          size="sm"
          style={{ width: "auto" }}
          aria-label="Invite for"
          value={scopeKey}
          onChange={(e) => setScopeKey(e.target.value)}
        >
          <option value="">Choose where…</option>
          {scopes.map((s) => (
            <option key={`${s.type}:${s.id}`} value={`${s.type}:${s.id}`}>
              {s.label}
            </option>
          ))}
        </Form.Select>
        <Button
          size="sm"
          onClick={submit}
          disabled={
            !email.trim() || !name.trim() || !scopeKey || invite.isPending
          }
        >
          Invite
        </Button>
        <Button
          size="sm"
          variant="outline-secondary"
          onClick={() => setOpen(false)}
        >
          Cancel
        </Button>
      </div>
      {invite.isError && (
        <Alert variant="danger" className="small mt-2 mb-0">
          {apiErrorMessage(invite.error, "The invitation could not be made.")}
        </Alert>
      )}
    </div>
  );
}
