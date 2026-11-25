import { useState, type FormEvent } from 'react'
import { Alert, Badge, Button, Card, Col, Form, InputGroup, ListGroup, Row, Spinner } from 'react-bootstrap'
import {
  useAddDeployment,
  useLmsSettings,
  useRegisterLms,
  useRemoveDeployment,
  useUpdateLms,
  type LmsPlatform,
} from '@/api/hooks/useAdmin'
import { apiErrorMessage } from '@/lib/apiError'

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Form.Group className="mb-2" controlId={`tool-${label}`}>
      <Form.Label className="small mb-1">{label}</Form.Label>
      <InputGroup size="sm">
        <Form.Control readOnly value={value} onFocus={(e) => e.target.select()} />
        <Button
          variant="outline-secondary"
          onClick={() => {
            navigator.clipboard?.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
          aria-label={`Copy ${label}`}
        >
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </InputGroup>
    </Form.Group>
  )
}

export default function LmsView() {
  const lms = useLmsSettings()
  const [registering, setRegistering] = useState(false)
  if (lms.isLoading) return <Spinner animation="border" role="status"><span className="visually-hidden">Loading…</span></Spinner>
  if (lms.isError || !lms.data) return <Alert variant="danger">{apiErrorMessage(lms.error, 'LMS settings could not be loaded.')}</Alert>
  const { tool, platforms } = lms.data

  return (
    <>
      <Card className="mb-4">
        <Card.Body>
          <Card.Title as="h2" className="h5">Register Stacks in your LMS</Card.Title>
          <p className="small text-body-secondary">
            Add Stacks to your LMS as an LTI 1.3 tool with these addresses. Then register the LMS below, using the
            details it shows you.
          </p>
          <Row>
            <Col md={6}><CopyRow label="OpenID Connect login URL" value={tool.login_url} /></Col>
            <Col md={6}><CopyRow label="Redirect URL" value={tool.redirect_url} /></Col>
            <Col md={6}><CopyRow label="Target link URI" value={tool.target_link_uri} /></Col>
            <Col md={6}><CopyRow label="Keyset (JWKS) URL" value={tool.jwks_url} /></Col>
          </Row>
        </Card.Body>
      </Card>

      <h2 className="h4">Registered LMS</h2>
      {platforms.length === 0 && <p className="text-body-secondary">None yet.</p>}
      {platforms.map((p) => (
        <PlatformCard key={p.id} platform={p} />
      ))}

      {registering ? (
        <RegisterForm onDone={() => setRegistering(false)} />
      ) : (
        <Button variant="outline-primary" onClick={() => setRegistering(true)}>
          Register an LMS
        </Button>
      )}
    </>
  )
}

function PlatformCard({ platform }: { platform: LmsPlatform }) {
  const [deployment, setDeployment] = useState('')
  const update = useUpdateLms()
  const add = useAddDeployment()
  const remove = useRemoveDeployment()
  const error = update.error || add.error || remove.error

  return (
    <Card className="mb-3">
      <Card.Body>
        <div className="d-flex justify-content-between align-items-start gap-2">
          <div>
            <Card.Title as="h3" className="h6 mb-1">
              {platform.issuer}{' '}
              <Badge bg={platform.is_active ? 'success' : 'secondary'}>{platform.is_active ? 'On' : 'Off'}</Badge>
            </Card.Title>
            <div className="small text-body-secondary">
              Client ID {platform.client_id} · {platform.people} {platform.people === 1 ? 'person has' : 'people have'} opened
              Stacks from it
            </div>
          </div>
          <Form.Check
            type="switch"
            id={`lms-${platform.id}-active`}
            label="Allow launches"
            checked={platform.is_active}
            onChange={(e) => update.mutate({ id: platform.id, is_active: e.target.checked })}
          />
        </div>
        <dl className="small mt-2 mb-2 row">
          <dt className="col-sm-3">Login</dt><dd className="col-sm-9 text-break">{platform.auth_login_url}</dd>
          <dt className="col-sm-3">Token</dt><dd className="col-sm-9 text-break">{platform.auth_token_url}</dd>
          <dt className="col-sm-3">Keyset</dt><dd className="col-sm-9 text-break">{platform.jwks_url}</dd>
        </dl>
        <h4 className="h6">Deployments</h4>
        <ListGroup className="mb-2">
          {platform.deployments.map((d) => (
            <ListGroup.Item key={d.id} className="d-flex justify-content-between align-items-center small">
              <span>
                {d.deployment_id} {d.label && <span className="text-body-secondary">({d.label})</span>}{' '}
                {!d.is_active && <Badge bg="secondary">Off</Badge>}
              </span>
              {d.is_active && (
                <Button size="sm" variant="outline-secondary" onClick={() => remove.mutate({ platformId: platform.id, id: d.id })}>
                  Turn off
                </Button>
              )}
            </ListGroup.Item>
          ))}
        </ListGroup>
        <Form
          onSubmit={(e) => {
            e.preventDefault()
            add.mutate({ platformId: platform.id, deployment_id: deployment.trim() }, { onSuccess: () => setDeployment('') })
          }}
          style={{ maxWidth: '28rem' }}
        >
          <InputGroup size="sm">
            <Form.Control aria-label="Deployment ID to add" placeholder="Deployment ID" value={deployment} onChange={(e) => setDeployment(e.target.value)} />
            <Button type="submit" variant="outline-primary" disabled={!deployment.trim() || add.isPending}>
              Add deployment
            </Button>
          </InputGroup>
        </Form>
        {error && <Alert variant="danger" className="small mt-2 mb-0">{apiErrorMessage(error, 'That didn’t work.')}</Alert>}
      </Card.Body>
    </Card>
  )
}

const REGISTRATION_FIELDS = [
  ['issuer', 'Issuer', 'https://yourschool.brightspace.com'],
  ['client_id', 'Client ID', ''],
  ['auth_login_url', 'OpenID Connect authentication endpoint', 'https://…/d2l/lti/authenticate'],
  ['auth_token_url', 'OAuth2 access token URL', 'https://auth.brightspace.com/core/connect/token'],
  ['jwks_url', 'LMS keyset URL', 'https://…/.well-known/jwks'],
] as const

function RegisterForm({ onDone }: { onDone: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [deployments, setDeployments] = useState('')
  const register = useRegisterLms()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    register.mutate(
      {
        issuer: values.issuer ?? '',
        client_id: values.client_id ?? '',
        auth_login_url: values.auth_login_url ?? '',
        auth_token_url: values.auth_token_url ?? '',
        jwks_url: values.jwks_url ?? '',
        deployment_ids: deployments.split(/[\s,]+/).filter(Boolean),
      },
      { onSuccess: onDone }
    )
  }
  return (
    <Card className="mb-3">
      <Card.Body>
        <Card.Title as="h3" className="h6">Register an LMS</Card.Title>
        <p className="small text-body-secondary">Copy these from the LMS after adding Stacks as a tool there.</p>
        <Form onSubmit={submit} noValidate>
          {REGISTRATION_FIELDS.map(([name, label, placeholder]) => (
            <Form.Group key={name} className="mb-2" controlId={`register-${name}`}>
              <Form.Label className="small mb-1">{label}</Form.Label>
              <Form.Control size="sm" value={values[name] ?? ''} placeholder={placeholder} onChange={(e) => setValues((v) => ({ ...v, [name]: e.target.value }))} />
            </Form.Group>
          ))}
          <Form.Group className="mb-3" controlId="register-deployments">
            <Form.Label className="small mb-1">Deployment IDs</Form.Label>
            <Form.Control size="sm" value={deployments} onChange={(e) => setDeployments(e.target.value)} placeholder="One or more, separated by spaces" />
          </Form.Group>
          {register.isError && <Alert variant="danger" className="small">{apiErrorMessage(register.error, 'The LMS could not be registered.')}</Alert>}
          <div className="d-flex gap-2">
            <Button type="submit" disabled={register.isPending}>{register.isPending ? 'Registering…' : 'Register'}</Button>
            <Button variant="outline-secondary" onClick={onDone}>Cancel</Button>
          </div>
        </Form>
      </Card.Body>
    </Card>
  )
}
