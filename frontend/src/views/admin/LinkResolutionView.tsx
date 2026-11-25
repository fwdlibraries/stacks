import { useState, type FormEvent } from 'react'
import { Alert, Badge, Button, Form, InputGroup, ListGroup, Spinner } from 'react-bootstrap'
import { ArrowDown, ArrowUp } from '@phosphor-icons/react'
import {
  useLinkResolutionSettings,
  useSaveLinkResolution,
  useTryLinkResolution,
  type LinkResolutionSettings,
  type StepName,
} from '@/api/hooks/useAdmin'
import { apiErrorMessage } from '@/lib/apiError'
import { LinkTrace } from '@/components/citations/LinkCheck'

const STEPS: Record<StepName, { label: string; does: string; needs: string }> = {
  libkey: { label: 'LibKey', does: 'Article PDFs and pages, by DOI', needs: 'Needs a LibKey connection.' },
  alma: {
    label: 'Library link resolver',
    does: 'Your full-text subscriptions (Alma)',
    needs: 'Needs Primo settings (and Alma, or its address).',
  },
  open_access: { label: 'Open access', does: 'Free, legal copies (OpenAlex), by DOI', needs: '' },
}
const ALL: StepName[] = ['libkey', 'alma', 'open_access']

export default function LinkResolutionView() {
  const settings = useLinkResolutionSettings()
  if (settings.isLoading) return <Spinner animation="border" role="status"><span className="visually-hidden">Loading…</span></Spinner>
  if (settings.isError || !settings.data) {
    return <Alert variant="danger">{apiErrorMessage(settings.error, 'Settings could not be loaded.')}</Alert>
  }
  return (
    <>
      <StackForm key={JSON.stringify(settings.data)} settings={settings.data} />
      <TryIt />
    </>
  )
}

function StackForm({ settings }: { settings: LinkResolutionSettings }) {
  // Enabled steps in order, then the disabled ones
  const [order, setOrder] = useState<StepName[]>([...settings.stack, ...ALL.filter((s) => !settings.stack.includes(s))])
  const [enabled, setEnabled] = useState<Set<StepName>>(new Set(settings.stack))
  const [cacheHours, setCacheHours] = useState(String(settings.cache_ttl_seconds / 3600))
  const [timeout, setTimeoutSeconds] = useState(String(settings.step_timeout_seconds))
  const save = useSaveLinkResolution()

  const move = (i: number, by: number) =>
    setOrder((o) => {
      const next = [...o]
      ;[next[i], next[i + by]] = [next[i + by], next[i]]
      return next
    })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate({
      stack: order.filter((s) => enabled.has(s)),
      cache_ttl_seconds: Math.round(Number(cacheHours) * 3600),
      step_timeout_seconds: Number(timeout),
    })
  }

  return (
    <Form onSubmit={submit} className="mb-5" noValidate>
      <p className="text-body-secondary">
        When a student clicks a link, Stacks tries these in order and sends them to the first that finds the
        item. If none does, they get the catalogue record, the DOI, or the citation’s web address.
      </p>
      <ListGroup className="mb-3" aria-label="Resolver steps, in order">
        {order.map((step, i) => (
          <ListGroup.Item key={step} className="d-flex align-items-center gap-3">
            <Form.Check
              id={`step-${step}`}
              type="switch"
              checked={enabled.has(step)}
              onChange={(e) =>
                setEnabled((s) => {
                  const next = new Set(s)
                  if (e.target.checked) next.add(step)
                  else next.delete(step)
                  return next
                })
              }
              aria-label={`Use ${STEPS[step].label}`}
            />
            <div className="flex-grow-1">
              <div className="fw-semibold">
                {STEPS[step].label}{' '}
                {!settings.available[step] && (
                  <Badge bg="warning" text="dark" title={STEPS[step].needs}>
                    Not set up
                  </Badge>
                )}
              </div>
              <div className="small text-body-secondary">
                {STEPS[step].does}
                {!settings.available[step] && ` ${STEPS[step].needs} Skipped until then.`}
              </div>
            </div>
            <Button size="sm" variant="link" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move ${STEPS[step].label} up`}>
              <ArrowUp aria-hidden="true" />
            </Button>
            <Button
              size="sm"
              variant="link"
              disabled={i === order.length - 1}
              onClick={() => move(i, 1)}
              aria-label={`Move ${STEPS[step].label} down`}
            >
              <ArrowDown aria-hidden="true" />
            </Button>
          </ListGroup.Item>
        ))}
      </ListGroup>

      <div className="d-flex gap-4 flex-wrap mb-3">
        <Form.Group controlId="cache-hours">
          <Form.Label>Reuse a found link for (hours)</Form.Label>
          <Form.Control type="number" min={0} max={168} step="0.5" value={cacheHours} onChange={(e) => setCacheHours(e.target.value)} style={{ maxWidth: '8rem' }} />
          <Form.Text>Longer: fewer API calls, less current.</Form.Text>
        </Form.Group>
        <Form.Group controlId="step-timeout">
          <Form.Label>Give each step up to (seconds)</Form.Label>
          <Form.Control type="number" min={0.5} max={10} step="0.5" value={timeout} onChange={(e) => setTimeoutSeconds(e.target.value)} style={{ maxWidth: '8rem' }} />
          <Form.Text>A slower step is skipped.</Form.Text>
        </Form.Group>
      </div>

      {save.isError && (
        <Alert variant="danger" className="small">
          {apiErrorMessage(save.error, 'The settings could not be saved.')}
        </Alert>
      )}
      {save.isSuccess && <Alert variant="success" className="small">Saved. New clicks use these settings.</Alert>}
      <Button type="submit" disabled={save.isPending}>
        {save.isPending ? 'Saving…' : 'Save'}
      </Button>
    </Form>
  )
}

function TryIt() {
  const [query, setQuery] = useState('')
  const tryIt = useTryLinkResolution()
  return (
    <section aria-labelledby="try-heading">
      <h2 id="try-heading" className="h4">
        Try it
      </h2>
      <p className="small text-body-secondary">See where a student would land right now (uses saved settings).</p>
      <Form
        onSubmit={(e) => {
          e.preventDefault()
          if (query.trim()) tryIt.mutate(query.trim())
        }}
        style={{ maxWidth: '32rem' }}
      >
        <InputGroup>
          <Form.Control aria-label="DOI, ISBN or MMS ID to try" placeholder="DOI, ISBN or Alma MMS ID" value={query} onChange={(e) => setQuery(e.target.value)} />
          <Button type="submit" variant="outline-primary" disabled={!query.trim() || tryIt.isPending}>
            {tryIt.isPending ? 'Trying…' : 'Try'}
          </Button>
        </InputGroup>
      </Form>
      {tryIt.isError && (
        <Alert variant="danger" className="small mt-2">
          {apiErrorMessage(tryIt.error, 'That could not be tried.')}
        </Alert>
      )}
      {tryIt.data && <LinkTrace result={tryIt.data} />}
    </section>
  )
}
