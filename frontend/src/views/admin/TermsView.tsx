import { useState, type FormEvent } from 'react'
import { Alert, Button, Card, Col, Form, Row, Spinner, Table } from 'react-bootstrap'
import {
  useDeleteTerm,
  useSaveTerm,
  useSaveTermPattern,
  useTermsSettings,
  useTryTermPattern,
  type AdminTerm,
  type TermInput,
} from '@/api/hooks/useAdmin'
import { apiErrorMessage } from '@/lib/apiError'
import { ConfirmModal } from '@/components/common/ConfirmModal'
import { FieldLabel, FormModal } from '@/components/common/FormModal'

const formatDate = (iso: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—'

/** Administration › Terms: teaching terms, and how LMS course shells are coded. */
export default function TermsView() {
  const settings = useTermsSettings()
  const [editing, setEditing] = useState<AdminTerm | 'new' | null>(null)
  const [removing, setRemoving] = useState<AdminTerm | null>(null)
  const remove = useDeleteTerm()

  if (settings.isLoading) return <Spinner animation="border" role="status"><span className="visually-hidden">Loading…</span></Spinner>
  if (settings.isError || !settings.data) {
    return <Alert variant="danger">{apiErrorMessage(settings.error, 'Terms could not be loaded.')}</Alert>
  }
  const { terms, section_code_pattern } = settings.data

  return (
    <>
      <p className="text-body-secondary mt-n2 mb-4">
        Each term can have its own reading lists, copied from an earlier term. Terms are also added automatically
        when a course opens Stacks from the LMS in a term Stacks hasn’t seen.
      </p>

      <Card>
        <Card.Header className="bg-white d-flex justify-content-between align-items-center gap-3 flex-wrap">
          <Card.Title as="h2" className="h6 mb-0">Terms</Card.Title>
          <Button size="sm" onClick={() => setEditing('new')}>Add term</Button>
        </Card.Header>
        {terms.length === 0 ? (
          <Card.Body className="small text-body-secondary">No terms yet.</Card.Body>
        ) : (
          <Table responsive className="mb-0">
            <thead>
              <tr>
                <th scope="col">Term</th>
                <th scope="col">Code</th>
                <th scope="col">Dates</th>
                <th scope="col">Rollover</th>
                <th scope="col">Lists due</th>
                <th scope="col" className="text-end">Courses</th>
                <th scope="col"><span className="visually-hidden">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {terms.map((t) => (
                <tr key={t.id}>
                  <td className="fw-medium">{t.name}</td>
                  <td><code>{t.code}</code></td>
                  <td className="small text-nowrap">
                    {t.starts_on || t.ends_on ? `${formatDate(t.starts_on)} – ${formatDate(t.ends_on)}` : '—'}
                  </td>
                  <td className="small text-nowrap">{formatDate(t.rollover_on)}</td>
                  <td className="small text-nowrap">{formatDate(t.lists_due_on)}</td>
                  <td className="text-end tabular-nums">{t.offerings}</td>
                  <td className="text-end text-nowrap">
                    <Button size="sm" variant="outline-secondary" onClick={() => setEditing(t)} aria-label={`Edit ${t.name}`}>
                      Edit
                    </Button>
                    {t.offerings === 0 && (
                      <Button
                        size="sm"
                        variant="outline-danger"
                        className="ms-2"
                        onClick={() => { remove.reset(); setRemoving(t) }}
                        aria-label={`Remove ${t.name}`}
                      >
                        Remove
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <PatternCard key={section_code_pattern ?? ''} saved={section_code_pattern} />

      {editing && (
        <TermFormModal
          key={editing === 'new' ? 'new' : editing.id}
          term={editing === 'new' ? undefined : editing}
          onDone={() => setEditing(null)}
        />
      )}

      <ConfirmModal
        show={removing !== null}
        title="Remove term"
        confirmLabel="Remove term"
        confirmVariant="danger"
        isPending={remove.isPending}
        error={remove.error ? apiErrorMessage(remove.error, 'The term could not be removed.') : null}
        onConfirm={() => removing && remove.mutate(removing.id, { onSuccess: () => setRemoving(null) })}
        onCancel={() => setRemoving(null)}
      >
        Remove <strong>{removing?.name}</strong>? No courses use it yet.
      </ConfirmModal>
    </>
  )
}

const DATES: { key: keyof Pick<TermInput, 'starts_on' | 'ends_on' | 'rollover_on' | 'lists_due_on'>; label: string; help?: string }[] = [
  { key: 'starts_on', label: 'Starts' },
  { key: 'ends_on', label: 'Ends' },
  { key: 'rollover_on', label: 'Rollover', help: 'When lists are copied for this term.' },
  { key: 'lists_due_on', label: 'Lists due', help: 'When lists should be ready for review.' },
]

function TermFormModal({ term, onDone }: { term?: AdminTerm; onDone: () => void }) {
  const save = useSaveTerm()
  const [input, setInput] = useState<TermInput>({
    code: term?.code ?? '',
    name: term?.name ?? '',
    starts_on: term?.starts_on ?? null,
    ends_on: term?.ends_on ?? null,
    rollover_on: term?.rollover_on ?? null,
    lists_due_on: term?.lists_due_on ?? null,
  })
  const [touched, setTouched] = useState(false)
  const set = (patch: Partial<TermInput>) => setInput((i) => ({ ...i, ...patch }))
  const codeLocked = Boolean(term && term.offerings > 0)

  const submit = () => {
    setTouched(true)
    if (!input.code.trim() || !input.name.trim()) return
    save.mutate({ ...input, id: term?.id }, { onSuccess: onDone })
  }

  return (
    <FormModal
      show
      title={term ? 'Edit term' : 'Add term'}
      submitLabel={term ? 'Save term' : 'Add term'}
      isPending={save.isPending}
      error={save.error ? apiErrorMessage(save.error, 'The term could not be saved.') : null}
      onSubmit={submit}
      onCancel={onDone}
    >
      <Row className="g-3 mb-3">
        <Col sm={7}>
          <Form.Group controlId="term-name">
            <FieldLabel required>Name</FieldLabel>
            <Form.Control
              value={input.name}
              onChange={(e) => set({ name: e.target.value })}
              isInvalid={touched && !input.name.trim()}
              placeholder="Fall 2027"
              autoFocus
            />
            <Form.Control.Feedback type="invalid">Enter a name.</Form.Control.Feedback>
          </Form.Group>
        </Col>
        <Col sm={5}>
          <Form.Group controlId="term-code">
            <FieldLabel required>Code</FieldLabel>
            <Form.Control
              value={input.code}
              onChange={(e) => set({ code: e.target.value })}
              isInvalid={touched && !input.code.trim()}
              disabled={codeLocked}
              placeholder="202710"
            />
            <Form.Control.Feedback type="invalid">Enter a code.</Form.Control.Feedback>
            <Form.Text>
              {codeLocked ? 'Courses use this code (it’s in student links), so it can’t change.' : 'Your SIS term code, if it has one.'}
            </Form.Text>
          </Form.Group>
        </Col>
      </Row>
      <Row className="g-3">
        {DATES.map((d) => (
          <Col sm={6} key={d.key}>
            <Form.Group controlId={`term-${d.key}`}>
              <FieldLabel>{d.label}</FieldLabel>
              <Form.Control type="date" value={input[d.key] ?? ''} onChange={(e) => set({ [d.key]: e.target.value || null })} />
              {d.help && <Form.Text>{d.help}</Form.Text>}
            </Form.Group>
          </Col>
        ))}
      </Row>
    </FormModal>
  )
}

function PatternCard({ saved }: { saved: string | null }) {
  const [pattern, setPattern] = useState(saved ?? '')
  const [sample, setSample] = useState('')
  const save = useSaveTermPattern()
  const tryIt = useTryTermPattern()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate(pattern.trim() || null)
  }
  const result = tryIt.data

  return (
    <Card className="mt-4">
      <Card.Header className="bg-white">
        <Card.Title as="h2" className="h6 mb-0">LMS course codes</Card.Title>
        <div className="small text-body-secondary mt-1">
          How your LMS codes live course shells, so a launch finds its term (and section) from the code.
        </div>
      </Card.Header>
      <Card.Body>
        <Form onSubmit={submit}>
          <Form.Group controlId="section-code-pattern" className="mb-3">
            <FieldLabel>Pattern</FieldLabel>
            <Form.Control
              value={pattern}
              onChange={(e) => { setPattern(e.target.value); save.reset(); tryIt.reset() }}
              placeholder="{crn}.{term}"
              className="font-monospace"
            />
            <Form.Text>
              Use <code>{'{term}'}</code> for the term code, and optionally <code>{'{crn}'}</code>,{' '}
              <code>{'{section}'}</code> or <code>{'{course}'}</code>. Everything else must match exactly. Leave blank
              if your shells aren’t coded by term; the LMS can send a <code>term</code> custom parameter instead.
            </Form.Text>
          </Form.Group>
          {save.isError && <Alert variant="danger" className="small">{apiErrorMessage(save.error, 'The pattern could not be saved.')}</Alert>}
          {save.isSuccess && <Alert variant="success" className="small">Saved.</Alert>}
          <Button type="submit" disabled={save.isPending || pattern.trim() === (saved ?? '')}>Save pattern</Button>
        </Form>

        <hr className="my-4" />

        <Form
          onSubmit={(e) => {
            e.preventDefault()
            if (sample.trim()) tryIt.mutate({ section_code_pattern: pattern.trim() || null, code: sample.trim() })
          }}
        >
          <Form.Group controlId="section-code-sample">
            <FieldLabel>Try a course code</FieldLabel>
            <div className="d-flex gap-2">
              <Form.Control value={sample} onChange={(e) => setSample(e.target.value)} placeholder="40112.202710" />
              <Button type="submit" variant="outline-primary" disabled={!sample.trim() || tryIt.isPending}>Try</Button>
            </div>
          </Form.Group>
        </Form>
        {tryIt.isError && <Alert variant="danger" className="small mt-3 mb-0">{apiErrorMessage(tryIt.error, 'Couldn’t try the pattern.')}</Alert>}
        {result && (
          <div className="small mt-3" role="status">
            {result.error ? (
              <span className="text-danger">{result.error}</span>
            ) : result.matches ? (
              <>
                Term <code>{result.term}</code>
                {result.term_name ? ` (${result.term_name})` : ' (a new term: it would be added)'}
                {result.crn && <> · CRN <code>{result.crn}</code></>}
                {result.section && <> · section <code>{result.section}</code></>}
                {result.course && <> · course <code>{result.course}</code></>}
              </>
            ) : (
              'Doesn’t match the pattern: Stacks would use the term custom parameter instead.'
            )}
          </div>
        )}
      </Card.Body>
    </Card>
  )
}
