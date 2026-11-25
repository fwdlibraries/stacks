import { useState, type FormEvent } from 'react'
import { Alert, Badge, Button, Card, Col, Form, Row, Spinner } from 'react-bootstrap'
import {
  useLibrarySources,
  useRemoveSource,
  useSaveSource,
  useTestSource,
  type LibrarySource,
  type SourceKind,
} from '@/api/hooks/useAdmin'
import { apiErrorMessage } from '@/lib/apiError'

interface Field {
  name: string
  label: string
  help?: string
  options?: { value: string; label: string }[]
  placeholder?: string
  optional?: boolean
  type?: 'number'
}

const REGIONS = [
  { value: 'na', label: 'North America' },
  { value: 'eu', label: 'Europe' },
  { value: 'ap', label: 'Asia Pacific' },
  { value: 'aps', label: 'Asia Pacific (Singapore)' },
  { value: 'ca', label: 'Canada' },
  { value: 'cn', label: 'China' },
]

const KINDS: Record<SourceKind, { title: string; purpose: string; keyLabel: string; fields: Field[] }> = {
  alma: {
    title: 'Alma',
    purpose: 'Your catalogue: library records that stay up to date, and the link resolver.',
    keyLabel: 'API key (Bibs: read)',
    fields: [
      { name: 'region', label: 'API region', options: REGIONS },
      {
        name: 'resolver_url',
        label: 'Alma address',
        optional: true,
        placeholder: 'https://yourschool.alma.exlibrisgroup.com',
        help: 'For the link resolver. Leave empty to work it out from the Primo address.',
      },
    ],
  },
  primo: {
    title: 'Primo VE / NDE',
    purpose: 'Searching your discovery system, and links to records students can open.',
    keyLabel: 'API key (Primo)',
    fields: [
      { name: 'region', label: 'API region', options: REGIONS },
      { name: 'vid', label: 'View ID', placeholder: '01ABC_INST:MAIN' },
      { name: 'tab', label: 'Search tab', placeholder: 'Everything' },
      { name: 'scope', label: 'Search scope', placeholder: 'MyInst_and_CI' },
      { name: 'discovery_url', label: 'Discovery address', placeholder: 'https://abc.primo.exlibrisgroup.com' },
      {
        name: 'interface',
        label: 'Interface',
        options: [
          { value: 'nde', label: 'NDE (Next Discovery Experience)' },
          { value: 've', label: 'VE (classic)' },
        ],
      },
    ],
  },
  libkey: {
    title: 'LibKey',
    purpose: 'One-click full text for articles (Third Iron).',
    keyLabel: 'API access token',
    fields: [{ name: 'library_id', label: 'Library ID', type: 'number', placeholder: '1234' }],
  },
}

const DEFAULTS: Record<SourceKind, Record<string, string>> = {
  alma: { region: 'na' },
  primo: { region: 'na', tab: 'Everything', scope: 'MyInst_and_CI', interface: 'nde' },
  libkey: {},
}

export default function ConnectionsView() {
  const sources = useLibrarySources()
  if (sources.isLoading) return <Spinner animation="border" role="status"><span className="visually-hidden">Loading…</span></Spinner>
  if (sources.isError || !sources.data) {
    return <Alert variant="danger">{apiErrorMessage(sources.error, 'Connections could not be loaded.')}</Alert>
  }
  return (
    <>
      <p className="text-body-secondary">
        Keys are stored encrypted and never shown again. Leave a key blank to keep the saved one.
      </p>
      {sources.data.map((source) => (
        <ConnectionCard key={`${source.kind}-${source.updated_at ?? 'new'}`} source={source} />
      ))}
    </>
  )
}

function ConnectionCard({ source }: { source: LibrarySource }) {
  const kind = KINDS[source.kind]
  const initial = Object.fromEntries(
    kind.fields.map((f) => [f.name, String(source.config[f.name] ?? DEFAULTS[source.kind][f.name] ?? '')])
  )
  const [values, setValues] = useState<Record<string, string>>(initial)
  const [apiKey, setApiKey] = useState('')
  const [active, setActive] = useState(source.configured ? source.is_active : true)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const save = useSaveSource(source.kind)
  const test = useTestSource(source.kind)
  const remove = useRemoveSource(source.kind)

  const config = () =>
    Object.fromEntries(
      kind.fields
        .filter((f) => values[f.name]?.trim() || !f.optional)
        .map((f) => [f.name, f.type === 'number' ? Number(values[f.name]) : values[f.name].trim()])
    )

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate({ config: config(), api_key: apiKey.trim() || undefined, is_active: active })
  }
  const error = save.error || remove.error || test.error
  const id = (name: string) => `${source.kind}-${name}`

  return (
    <Card className="mb-4">
      <Card.Body>
        <div className="d-flex justify-content-between align-items-start">
          <div>
            <Card.Title as="h2" className="h5 mb-1">
              {kind.title}{' '}
              {source.configured ? (
                <Badge bg={source.is_active ? 'success' : 'secondary'}>{source.is_active ? 'On' : 'Off'}</Badge>
              ) : (
                <Badge bg="light" text="dark">Not connected</Badge>
              )}
            </Card.Title>
            <p className="small text-body-secondary">{kind.purpose}</p>
          </div>
        </div>
        <Form onSubmit={submit} noValidate>
          <Row>
            {kind.fields.map((f) => (
              <Col md={6} key={f.name}>
                <Form.Group className="mb-3" controlId={id(f.name)}>
                  <Form.Label>
                    {f.label}
                    {f.optional && <span className="text-body-secondary fw-normal"> (optional)</span>}
                  </Form.Label>
                  {f.options ? (
                    <Form.Select
                      value={values[f.name]}
                      onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                    >
                      {f.options.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </Form.Select>
                  ) : (
                    <Form.Control
                      type={f.type ?? 'text'}
                      value={values[f.name]}
                      placeholder={f.placeholder}
                      onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                    />
                  )}
                  {f.help && <Form.Text>{f.help}</Form.Text>}
                </Form.Group>
              </Col>
            ))}
            <Col md={6}>
              <Form.Group className="mb-3" controlId={id('key')}>
                <Form.Label>{kind.keyLabel}</Form.Label>
                <Form.Control
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  placeholder={source.key_set ? 'Saved (leave blank to keep)' : ''}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              </Form.Group>
            </Col>
          </Row>
          <Form.Check
            id={id('active')}
            type="switch"
            className="mb-3"
            label="Use this connection"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
          />

          {test.data && (
            <Alert variant={test.data.ok ? 'success' : 'warning'} className="small">
              {test.data.message}
            </Alert>
          )}
          {error && (
            <Alert variant="danger" className="small">
              {apiErrorMessage(error, 'That didn’t work.')}
            </Alert>
          )}
          {save.isSuccess && !save.isPending && <Alert variant="success" className="small">Saved.</Alert>}

          <div className="d-flex gap-2">
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? 'Saving…' : source.configured ? 'Save' : 'Connect'}
            </Button>
            <Button
              variant="outline-secondary"
              disabled={test.isPending || (!apiKey.trim() && !source.key_set)}
              onClick={() => test.mutate({ config: config(), api_key: apiKey.trim() || undefined })}
            >
              {test.isPending ? 'Testing…' : 'Test connection'}
            </Button>
            {source.configured && !confirmRemove && (
              <Button variant="outline-danger" className="ms-auto" onClick={() => setConfirmRemove(true)}>
                Remove
              </Button>
            )}
            {source.configured && confirmRemove && (
              <span className="ms-auto d-flex gap-2 align-items-center small">
                Remove the {kind.title} connection and its key?
                <Button variant="danger" size="sm" disabled={remove.isPending} onClick={() => remove.mutate()}>
                  Remove
                </Button>
                <Button variant="outline-secondary" size="sm" onClick={() => setConfirmRemove(false)}>
                  Keep
                </Button>
              </span>
            )}
          </div>
        </Form>
      </Card.Body>
    </Card>
  )
}
