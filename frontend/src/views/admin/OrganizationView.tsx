import { useState, type FormEvent } from 'react'
import { Alert, Badge, Button, Form, InputGroup, ListGroup, Spinner } from 'react-bootstrap'
import {
  useAddDomain,
  useMakeDomainPrimary,
  useOrganizationSettings,
  useRemoveDomain,
  useUpdateOrganization,
  type OrganizationSettings,
} from '@/api/hooks/useAdmin'
import { apiErrorMessage } from '@/lib/apiError'
import { FieldLabel } from '@/components/common/FormModal'

export default function OrganizationView() {
  const org = useOrganizationSettings()
  if (org.isLoading) return <Spinner animation="border" role="status"><span className="visually-hidden">Loading…</span></Spinner>
  if (org.isError || !org.data) return <Alert variant="danger">{apiErrorMessage(org.error, 'Settings could not be loaded.')}</Alert>
  return (
    <>
      {/* key: reset the form when the saved settings change */}
      <SettingsForm key={JSON.stringify(org.data)} org={org.data} />
      <Domains org={org.data} />
    </>
  )
}

function SettingsForm({ org }: { org: OrganizationSettings }) {
  const [name, setName] = useState(org.name)
  const [useDefaultOrigins, setUseDefaultOrigins] = useState(org.lms_origins === null)
  const [origins, setOrigins] = useState((org.lms_origins ?? org.default_lms_origins).join('\n'))
  const [contact, setContact] = useState(org.contact_email ?? '')
  const update = useUpdateOrganization()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    update.mutate({
      name,
      lms_origins: useDefaultOrigins
        ? null
        : origins
            .split(/[\s,]+/)
            .map((o) => o.trim())
            .filter(Boolean),
      contact_email: contact.trim() || null,
    })
  }

  return (
    <Form onSubmit={submit} className="mb-5" noValidate>
      <Form.Group className="mb-3" controlId="org-name" style={{ maxWidth: '28rem' }}>
        <FieldLabel required>Name</FieldLabel>
        <Form.Control value={name} onChange={(e) => setName(e.target.value)} />
      </Form.Group>

      <fieldset className="mb-3">
        <legend className="form-label fs-6 fw-semibold">LMS sites that can show Stacks</legend>
        <p className="small text-body-secondary mb-2">
          Course pages in these learning management systems can embed reading lists, e.g.
          https://yourschool.brightspace.com.
        </p>
        <Form.Check
          id="org-origins-default"
          type="checkbox"
          className="mb-2"
          label={
            org.default_lms_origins.length
              ? `Use this installation's default (${org.default_lms_origins.join(', ')})`
              : "Use this installation's default (none)"
          }
          checked={useDefaultOrigins}
          onChange={(e) => setUseDefaultOrigins(e.target.checked)}
        />
        {!useDefaultOrigins && (
          <Form.Control
            as="textarea"
            rows={3}
            aria-label="LMS sites, one per line"
            value={origins}
            onChange={(e) => setOrigins(e.target.value)}
            placeholder="https://yourschool.brightspace.com"
          />
        )}
      </fieldset>

      <Form.Group className="mb-3" controlId="org-contact" style={{ maxWidth: '28rem' }}>
        <Form.Label>Contact address for metadata services</Form.Label>
        <Form.Control
          type="email"
          value={contact}
          onChange={(e) => setContact(e.target.value)}
          placeholder={org.default_contact_email ?? 'library-systems@example.edu'}
        />
        <Form.Text>
          Sent to Crossref and OpenAlex with lookups, so they serve them faster.
          {org.default_contact_email && !contact && ` Using the installation default, ${org.default_contact_email}.`}
        </Form.Text>
      </Form.Group>

      {update.isError && (
        <Alert variant="danger" className="small">
          {apiErrorMessage(update.error, 'The settings could not be saved.')}
        </Alert>
      )}
      {update.isSuccess && <Alert variant="success" className="small">Saved.</Alert>}
      <Button type="submit" disabled={update.isPending || !name.trim()}>
        {update.isPending ? 'Saving…' : 'Save settings'}
      </Button>
    </Form>
  )
}

function Domains({ org }: { org: OrganizationSettings }) {
  const [hostname, setHostname] = useState('')
  const add = useAddDomain()
  const primary = useMakeDomainPrimary()
  const remove = useRemoveDomain()
  const error = add.error || primary.error || remove.error

  return (
    <section aria-labelledby="domains-heading">
      <h2 id="domains-heading" className="h4">
        Web address
      </h2>
      <p className="small text-body-secondary">
        People reach your Stacks at <strong>{org.address}</strong>. LMS tool registrations use this address.
        {!org.can_manage_domains && ' Your Stacks provider manages these addresses.'}
      </p>
      {org.domains.length > 0 && (
        <ListGroup className="mb-3">
          {org.domains.map((d) => (
            <ListGroup.Item key={d.id} className="d-flex justify-content-between align-items-center">
              <span>
                {d.hostname} {d.is_primary && <Badge bg="secondary">Primary</Badge>}
              </span>
              {org.can_manage_domains && (
                <span className="d-flex gap-2">
                  {!d.is_primary && (
                    <Button size="sm" variant="outline-secondary" onClick={() => primary.mutate(d.id)}>
                      Make primary
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline-danger"
                    onClick={() => remove.mutate(d.id)}
                    aria-label={`Remove ${d.hostname}`}
                  >
                    Remove
                  </Button>
                </span>
              )}
            </ListGroup.Item>
          ))}
        </ListGroup>
      )}
      {org.can_manage_domains && (
        <Form
          onSubmit={(e) => {
            e.preventDefault()
            add.mutate(hostname, { onSuccess: () => setHostname('') })
          }}
          style={{ maxWidth: '28rem' }}
        >
          <InputGroup>
            <Form.Control
              aria-label="Add a hostname"
              placeholder="stacks.library.example.edu"
              value={hostname}
              onChange={(e) => setHostname(e.target.value)}
            />
            <Button type="submit" variant="outline-primary" disabled={!hostname.trim() || add.isPending}>
              Add
            </Button>
          </InputGroup>
        </Form>
      )}
      {error && (
        <Alert variant="danger" className="small mt-2">
          {apiErrorMessage(error, 'The address could not be changed.')}
        </Alert>
      )}
    </section>
  )
}
