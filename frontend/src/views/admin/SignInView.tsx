import { useState, type FormEvent } from "react";
import {
  Alert,
  Button,
  Card,
  CloseButton,
  Col,
  Form,
  InputGroup,
  Row,
  Spinner,
} from "react-bootstrap";
import {
  useRemoveSso,
  useSaveSso,
  useSsoSettings,
  useTestSso,
  type SsoSettings,
} from "@/api/hooks/useAdmin";
import { apiErrorMessage } from "@/lib/apiError";

const ROLES = ["Administrator", "Librarian", "Instructor", "Viewer"];

export default function SignInView() {
  const settings = useSsoSettings();
  if (settings.isLoading)
    return (
      <Spinner animation="border" role="status">
        <span className="visually-hidden">Loading…</span>
      </Spinner>
    );
  if (settings.isError || !settings.data)
    return (
      <Alert variant="danger">
        {apiErrorMessage(settings.error, "Settings could not be loaded.")}
      </Alert>
    );
  return <SsoForm key={JSON.stringify(settings.data)} saved={settings.data} />;
}

function SsoForm({ saved }: { saved: SsoSettings }) {
  const [issuer, setIssuer] = useState(saved.issuer ?? "");
  const [clientId, setClientId] = useState(saved.client_id ?? "");
  const [secret, setSecret] = useState("");
  const [label, setLabel] = useState(
    saved.button_label ?? "Sign in with your institution",
  );
  const [domains, setDomains] = useState(saved.allowed_domains.join(", "));
  const [allowSignup, setAllowSignup] = useState(saved.allow_signup);
  const [requireMfa, setRequireMfa] = useState(saved.require_mfa);
  const [disablePasswords, setDisablePasswords] = useState(
    saved.disable_passwords,
  );
  const [active, setActive] = useState(
    saved.configured ? saved.is_active : true,
  );
  const [mapping, setMapping] = useState<[string, string][]>(
    Object.entries(saved.role_mapping),
  );
  const [confirmRemove, setConfirmRemove] = useState(false);
  const save = useSaveSso();
  const test = useTestSso();
  const remove = useRemoveSso();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate({
      issuer: issuer.trim(),
      client_id: clientId.trim(),
      client_secret: secret.trim() || undefined,
      button_label: label.trim(),
      allowed_domains: domains.split(/[\s,]+/).filter(Boolean),
      allow_signup: allowSignup,
      require_mfa: requireMfa,
      disable_passwords: disablePasswords,
      role_mapping: Object.fromEntries(mapping.filter(([k]) => k.trim())),
      is_active: active,
    });
  };
  const error = save.error || remove.error || test.error;

  return (
    <>
      <p className="text-body-secondary">
        Let people sign in with your institution’s account (OpenID Connect:
        Microsoft Entra ID, Google, Okta and others). People who open Stacks
        from your LMS are already signed in and don’t need this.
      </p>
      <Card className="mb-4">
        <Card.Body>
          <Form.Group controlId="sso-redirect">
            <Form.Label className="small">
              Redirect URI to register with your identity provider
            </Form.Label>
            <InputGroup size="sm">
              <Form.Control
                readOnly
                value={saved.redirect_uri}
                onFocus={(e) => e.target.select()}
              />
              <Button
                variant="outline-secondary"
                onClick={() =>
                  navigator.clipboard?.writeText(saved.redirect_uri)
                }
              >
                Copy
              </Button>
            </InputGroup>
          </Form.Group>
        </Card.Body>
      </Card>

      <Form onSubmit={submit} noValidate>
        <Row>
          <Col md={8}>
            <Form.Group className="mb-3" controlId="sso-issuer">
              <Form.Label>Issuer</Form.Label>
              <Form.Control
                value={issuer}
                onChange={(e) => setIssuer(e.target.value)}
                placeholder="https://login.microsoftonline.com/<tenant ID>/v2.0"
              />
              <Form.Text>
                For Entra, use your tenant ID, not “common”.
              </Form.Text>
            </Form.Group>
          </Col>
          <Col md={4} className="d-flex align-items-start pt-md-4">
            <Button
              variant="outline-secondary"
              className="mt-md-2"
              disabled={!issuer.trim() || test.isPending}
              onClick={() => test.mutate(issuer.trim())}
            >
              {test.isPending ? "Checking…" : "Check provider"}
            </Button>
          </Col>
        </Row>
        {test.data && (
          <Alert
            variant={test.data.ok ? "success" : "warning"}
            className="small"
          >
            {test.data.message}
          </Alert>
        )}
        <Row>
          <Col md={6}>
            <Form.Group className="mb-3" controlId="sso-client">
              <Form.Label>Client ID (application ID)</Form.Label>
              <Form.Control
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
              />
            </Form.Group>
          </Col>
          <Col md={6}>
            <Form.Group className="mb-3" controlId="sso-secret">
              <Form.Label>Client secret</Form.Label>
              <Form.Control
                type="password"
                autoComplete="off"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                placeholder={
                  saved.secret_set ? "Saved (leave blank to keep)" : ""
                }
              />
            </Form.Group>
          </Col>
        </Row>
        <Row>
          <Col md={6}>
            <Form.Group className="mb-3" controlId="sso-label">
              <Form.Label>Button text</Form.Label>
              <Form.Control
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </Form.Group>
          </Col>
          <Col md={6}>
            <Form.Group className="mb-3" controlId="sso-domains">
              <Form.Label>Email domains</Form.Label>
              <Form.Control
                value={domains}
                onChange={(e) => setDomains(e.target.value)}
                placeholder="csp.edu"
              />
              <Form.Text>
                Invitations and new accounts must be in these domains.
              </Form.Text>
            </Form.Group>
          </Col>
        </Row>

        <fieldset className="mb-3">
          <legend className="form-label fs-6 fw-semibold">
            Who can sign in
          </legend>
          <Form.Check
            type="radio"
            name="signup"
            id="sso-invited"
            checked={!allowSignup}
            onChange={() => setAllowSignup(false)}
            label="Only people you invite (on the People tab)"
          />
          <Form.Check
            type="radio"
            name="signup"
            id="sso-anyone"
            checked={allowSignup}
            onChange={() => setAllowSignup(true)}
            label="Anyone in those domains (they start with no roles)"
          />
        </fieldset>
        <Form.Check
          className="mb-2"
          type="switch"
          id="sso-mfa"
          checked={requireMfa}
          onChange={(e) => setRequireMfa(e.target.checked)}
          label="Require multi-factor authentication (the provider must report it)"
        />
        <Form.Check
          className="mb-2"
          type="switch"
          id="sso-nopw"
          checked={disablePasswords}
          onChange={(e) => setDisablePasswords(e.target.checked)}
          label="Turn off Stacks passwords (system administrators keep theirs)"
        />
        <Form.Check
          className="mb-4"
          type="switch"
          id="sso-active"
          checked={active}
          onChange={(e) => setActive(e.target.checked)}
          label="Offer this sign-in"
        />

        <fieldset className="mb-4">
          <legend className="form-label fs-6 fw-semibold">
            Roles from your identity provider (optional)
          </legend>
          <p className="small text-body-secondary">
            For Entra, define app roles (e.g. Stacks.Librarian) and assign
            people or groups to them. Mapped roles apply to the whole
            organization and follow the provider: they’re added or removed at
            each sign-in.
          </p>
          {mapping.map(([claim, role], i) => (
            <div key={i} className="d-flex gap-2 align-items-center mb-2">
              <Form.Control
                size="sm"
                aria-label="Role claim value"
                placeholder="Stacks.Librarian"
                value={claim}
                style={{ maxWidth: "16rem" }}
                onChange={(e) =>
                  setMapping((m) =>
                    m.map((row, j) =>
                      j === i ? [e.target.value, row[1]] : row,
                    ),
                  )
                }
              />
              <span className="small">gives</span>
              <Form.Select
                size="sm"
                aria-label="Stacks role"
                value={role}
                style={{ width: "auto" }}
                onChange={(e) =>
                  setMapping((m) =>
                    m.map((row, j) =>
                      j === i ? [row[0], e.target.value] : row,
                    ),
                  )
                }
              >
                {ROLES.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </Form.Select>
              <CloseButton
                aria-label={`Remove mapping ${claim}`}
                onClick={() => setMapping((m) => m.filter((_, j) => j !== i))}
              />
            </div>
          ))}
          <Button
            size="sm"
            variant="link"
            className="p-0"
            onClick={() => setMapping((m) => [...m, ["", "Librarian"]])}
          >
            Add a mapping
          </Button>
        </fieldset>

        {error && (
          <Alert variant="danger" className="small">
            {apiErrorMessage(error, "That didn’t work.")}
          </Alert>
        )}
        {save.isSuccess && (
          <Alert variant="success" className="small">
            Saved. Try it from a private window before turning passwords off.
          </Alert>
        )}
        <div className="d-flex gap-2">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          {saved.configured && !confirmRemove && (
            <Button
              variant="outline-danger"
              className="ms-auto"
              onClick={() => setConfirmRemove(true)}
            >
              Remove
            </Button>
          )}
          {saved.configured && confirmRemove && (
            <span className="ms-auto d-flex gap-2 align-items-center small">
              Remove single sign-on?
              <Button
                size="sm"
                variant="danger"
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
              >
                Remove
              </Button>
              <Button
                size="sm"
                variant="outline-secondary"
                onClick={() => setConfirmRemove(false)}
              >
                Keep
              </Button>
            </span>
          )}
        </div>
      </Form>
    </>
  );
}
