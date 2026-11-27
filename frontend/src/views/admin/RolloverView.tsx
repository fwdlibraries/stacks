import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Alert, Badge, Button, ButtonGroup, Card, Col, Form, Row, Spinner, Table } from 'react-bootstrap'
import { useTerms } from '@/api/hooks/useLists'
import {
  useBulkStatus,
  useForget,
  useImportPrimaries,
  useImportSections,
  usePrimaries,
  useRematch,
  useRemembered,
  useRolloverItems,
  useRolloverSettings,
  useSaveRolloverSettings,
  useTryPrimaryPattern,
  useUpdateItem,
  type ItemFilters,
  type MatchSource,
  type PrimariesImport,
  type RolloverItem,
  type RolloverSettings,
  type RolloverStatus,
  type SectionsImport,
} from '@/api/hooks/useRollover'
import { apiErrorMessage } from '@/lib/apiError'
import { FieldLabel, FormModal } from '@/components/common/FormModal'

const STATUS_LABELS: Record<RolloverStatus, string> = {
  needs_source: 'Needs a source',
  in_review: 'In review',
  approved: 'Approved',
  skipped: 'Skipped',
}
const STATUS_VARIANTS: Record<RolloverStatus, string> = {
  needs_source: 'warning',
  in_review: 'info',
  approved: 'success',
  skipped: 'secondary',
}
const SOURCE_LABELS: Record<MatchSource, string> = {
  manual: 'Chosen',
  file: 'Loader file',
  remembered: 'Remembered',
  rule: 'Code rule',
  only_one: 'Only one fits',
}

type View = 'all' | RolloverStatus | 'problems'

/** Administration › Rollover: an upcoming term's sections and where each one's list comes from. */
export default function RolloverView() {
  const terms = useTerms()
  const [termId, setTermId] = useState<string>()
  useEffect(() => {
    if (!termId && terms.data?.length) setTermId(terms.data[0].id)
  }, [termId, terms.data])

  if (terms.isLoading) return <Spinner animation="border" role="status"><span className="visually-hidden">Loading…</span></Spinner>
  if (terms.isError) return <Alert variant="danger">{apiErrorMessage(terms.error, 'Terms could not be loaded.')}</Alert>

  return (
    <>
      <p className="text-body-secondary mt-n2 mb-4">
        Import a term’s sections and your primary shells, then check where each section’s reading list will come from.
        Sections Stacks can’t match wait under <em>Needs a source</em>.
      </p>
      {!terms.data?.length ? (
        <Alert variant="info">Add the upcoming term under Administration › Terms first.</Alert>
      ) : (
        <>
          <Form.Group controlId="rollover-term" className="mb-4" style={{ maxWidth: 320 }}>
            <FieldLabel>Term</FieldLabel>
            <Form.Select value={termId} onChange={(e) => setTermId(e.target.value)}>
              {terms.data.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.code})</option>)}
            </Form.Select>
          </Form.Group>
          {termId && <Workspace key={termId} termId={termId} />}
        </>
      )}
      <ImportPrimariesCard />
      <SettingsCard />
      <RememberedCard />
    </>
  )
}

function Workspace({ termId }: { termId: string }) {
  const [view, setView] = useState<View>('needs_source')
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [choosing, setChoosing] = useState<RolloverItem | null>(null)
  const filters: ItemFilters = useMemo(
    () => ({
      ...(view === 'problems' ? { has_problems: true } : view === 'all' ? {} : { status: view }),
      ...(q ? { q } : {}),
    }),
    [view, q],
  )
  const items = useRolloverItems(termId, filters)
  const update = useUpdateItem()
  const bulk = useBulkStatus()
  const rematch = useRematch(termId)

  useEffect(() => setSelected(new Set()), [view, q])
  const data = items.data
  const total = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : 0
  const views: { key: View; label: string; n?: number }[] = [
    { key: 'needs_source', label: STATUS_LABELS.needs_source, n: data?.counts.needs_source },
    { key: 'in_review', label: STATUS_LABELS.in_review, n: data?.counts.in_review },
    { key: 'approved', label: STATUS_LABELS.approved, n: data?.counts.approved },
    { key: 'skipped', label: STATUS_LABELS.skipped, n: data?.counts.skipped },
    { key: 'problems', label: 'Has problems', n: data?.problems },
    { key: 'all', label: 'All', n: total },
  ]
  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const shown = data?.items ?? []
  const allSelected = shown.length > 0 && shown.every((i) => selected.has(i.id))
  const setBulk = (status: RolloverStatus) =>
    bulk.mutate({ ids: [...selected], status }, { onSuccess: () => setSelected(new Set()) })

  return (
    <>
      <ImportSectionsCard termId={termId} />

      <Card className="mb-4">
        <Card.Header className="bg-white d-flex justify-content-between align-items-center gap-3 flex-wrap">
          <Card.Title as="h2" className="h6 mb-0">Sections</Card.Title>
          <Button size="sm" variant="outline-secondary" onClick={() => rematch.mutate()} disabled={rematch.isPending || total === 0}>
            {rematch.isPending ? 'Matching…' : 'Match again'}
          </Button>
        </Card.Header>
        <Card.Body className="pb-0">
          <div className="d-flex flex-wrap gap-2 mb-3" role="group" aria-label="Show sections">
            {views.map((v) => (
              <Button
                key={v.key}
                size="sm"
                variant={view === v.key ? 'primary' : 'outline-secondary'}
                aria-pressed={view === v.key}
                onClick={() => setView(v.key)}
              >
                {v.label} <span className="tabular-nums">{v.n ?? ''}</span>
              </Button>
            ))}
          </div>
          <Form
            className="d-flex gap-2 mb-3"
            onSubmit={(e) => { e.preventDefault(); setQ(search.trim()) }}
            role="search"
          >
            <Form.Control
              size="sm"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Section, course or department"
              aria-label="Search sections"
              style={{ maxWidth: 320 }}
            />
            <Button size="sm" type="submit" variant="outline-primary">Search</Button>
            {q && <Button size="sm" variant="link" onClick={() => { setSearch(''); setQ('') }}>Clear</Button>}
          </Form>
          {selected.size > 0 && (
            <div className="d-flex align-items-center gap-2 mb-3 small" role="region" aria-label="Selected sections">
              <span>{selected.size} selected</span>
              <ButtonGroup size="sm">
                <Button variant="outline-success" onClick={() => setBulk('approved')} disabled={bulk.isPending}>Approve</Button>
                <Button variant="outline-secondary" onClick={() => setBulk('skipped')} disabled={bulk.isPending}>Skip</Button>
                <Button variant="outline-secondary" onClick={() => setBulk('in_review')} disabled={bulk.isPending}>Back to review</Button>
              </ButtonGroup>
            </div>
          )}
          {bulk.data && bulk.data.refused > 0 && (
            <Alert variant="warning" className="small">
              {bulk.data.refused} section{bulk.data.refused === 1 ? '' : 's'} weren’t approved: choose a primary first.
            </Alert>
          )}
          {(update.isError || bulk.isError || rematch.isError) && (
            <Alert variant="danger" className="small">
              {apiErrorMessage(update.error ?? bulk.error ?? rematch.error, 'The change could not be saved.')}
            </Alert>
          )}
        </Card.Body>
        {items.isLoading ? (
          <Card.Body><Spinner size="sm" animation="border" role="status"><span className="visually-hidden">Loading…</span></Spinner></Card.Body>
        ) : items.isError ? (
          <Card.Body><Alert variant="danger" className="mb-0">{apiErrorMessage(items.error, 'Sections could not be loaded.')}</Alert></Card.Body>
        ) : shown.length === 0 ? (
          <Card.Body className="small text-body-secondary">
            {total === 0 ? 'No sections yet: import a course loader file for this term.' : 'No sections here.'}
          </Card.Body>
        ) : (
          <Table responsive className="mb-0 align-middle">
            <thead>
              <tr>
                <th scope="col">
                  <Form.Check
                    aria-label="Select all shown"
                    checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(shown.map((i) => i.id)))}
                  />
                </th>
                <th scope="col">Section</th>
                <th scope="col">Course</th>
                <th scope="col">Length</th>
                <th scope="col">Primary</th>
                <th scope="col">Status</th>
                <th scope="col"><span className="visually-hidden">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((item) => (
                <tr key={item.id}>
                  <td>
                    <Form.Check aria-label={`Select ${item.lms_code}`} checked={selected.has(item.id)} onChange={() => toggle(item.id)} />
                  </td>
                  <td><code>{item.lms_code}</code></td>
                  <td>
                    <div className="fw-medium">{item.course}</div>
                    <div className="small text-body-secondary">{item.course_name}</div>
                  </td>
                  <td className="small">{item.length ?? item.part_of_term ?? '—'}</td>
                  <td>
                    {item.primary ? (
                      <>
                        <code className="small">{item.primary.code}</code>
                        <div className="small text-body-secondary">{item.match_source && SOURCE_LABELS[item.match_source]}</div>
                      </>
                    ) : (
                      <span className="small text-body-secondary">—</span>
                    )}
                    {item.problems.map((p) => (
                      <div key={p} className="small text-danger">{p}</div>
                    ))}
                  </td>
                  <td><Badge bg={STATUS_VARIANTS[item.status]} text={item.status === 'needs_source' ? 'dark' : undefined}>{STATUS_LABELS[item.status]}</Badge></td>
                  <td className="text-end text-nowrap">
                    <Button size="sm" variant="outline-secondary" onClick={() => setChoosing(item)} aria-label={`Choose primary for ${item.lms_code}`}>
                      Primary…
                    </Button>
                    {item.status === 'in_review' && (
                      <Button
                        size="sm"
                        variant="outline-success"
                        className="ms-2"
                        onClick={() => update.mutate({ id: item.id, status: 'approved' })}
                        aria-label={`Approve ${item.lms_code}`}
                      >
                        Approve
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {data && data.total > shown.length && (
          <Card.Footer className="small text-body-secondary bg-white">
            Showing {shown.length} of {data.total}. Search to narrow the list.
          </Card.Footer>
        )}
      </Card>

      {choosing && <ChoosePrimaryModal item={choosing} onDone={() => setChoosing(null)} />}
    </>
  )
}

function ChoosePrimaryModal({ item, onDone }: { item: RolloverItem; onDone: () => void }) {
  const primaries = usePrimaries(item.course)
  const update = useUpdateItem()
  const [choice, setChoice] = useState<string | null>(item.primary?.id ?? null)
  const [remember, setRemember] = useState(true)
  const options = (primaries.data ?? []).filter((p) => p.course === item.course)

  return (
    <FormModal
      show
      title={`Primary for ${item.lms_code}`}
      submitLabel="Save"
      isPending={update.isPending}
      error={update.error ? apiErrorMessage(update.error, 'The choice could not be saved.') : null}
      onSubmit={() =>
        update.mutate({ id: item.id, set_primary: true, primary_id: choice, remember }, { onSuccess: onDone })
      }
      onCancel={onDone}
    >
      <p className="small text-body-secondary">
        {item.course} {item.course_name}
        {item.length && <> · length {item.length}</>}
        {item.file_primary_code && <> · the loader file says <code>{item.file_primary_code}</code></>}
      </p>
      {primaries.isLoading ? (
        <Spinner size="sm" animation="border" role="status"><span className="visually-hidden">Loading…</span></Spinner>
      ) : (
        <fieldset>
          <legend className="visually-hidden">Primary</legend>
          {options.length === 0 && (
            <p className="small">No primaries for {item.course} yet. Import your primary shells below the table.</p>
          )}
          {options.map((p) => (
            <Form.Check
              key={p.id}
              type="radio"
              id={`primary-${p.id}`}
              name="primary"
              checked={choice === p.id}
              onChange={() => setChoice(p.id)}
              label={<><code>{p.code}</code>{p.name && <span className="text-body-secondary"> {p.name}</span>}</>}
            />
          ))}
          <Form.Check
            type="radio"
            id="primary-none"
            name="primary"
            checked={choice === null}
            onChange={() => setChoice(null)}
            label="Let Stacks match it"
            className="mt-2"
          />
        </fieldset>
      )}
      {choice && (
        <Form.Check
          className="mt-3"
          id="primary-remember"
          checked={remember}
          onChange={(e) => setRemember(e.target.checked)}
          label={`Use this primary for ${item.course}${item.length ? ` (${item.length})` : ''} sections in later terms`}
        />
      )}
    </FormModal>
  )
}

function FilePicker({ id, label, help, pending, onFile }: {
  id: string; label: string; help: ReactNode; pending: boolean; onFile: (text: string) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  return (
    <Form
      onSubmit={async (e: FormEvent) => {
        e.preventDefault()
        if (file) onFile(await file.text())
      }}
    >
      <Form.Group controlId={id}>
        <FieldLabel>{label}</FieldLabel>
        <div className="d-flex gap-2">
          <Form.Control type="file" accept=".csv,.tsv,.txt,text/csv,text/plain" onChange={(e) => setFile((e.target as HTMLInputElement).files?.[0] ?? null)} />
          <Button type="submit" disabled={!file || pending}>{pending ? 'Importing…' : 'Import'}</Button>
        </div>
        <Form.Text>{help}</Form.Text>
      </Form.Group>
    </Form>
  )
}

function SkippedList({ skipped }: { skipped: { line: number; code: string; reason: string }[] }) {
  if (!skipped.length) return null
  return (
    <details className="mt-2">
      <summary>{skipped.length} row{skipped.length === 1 ? '' : 's'} skipped</summary>
      <ul className="mb-0 mt-1">
        {skipped.map((s) => <li key={`${s.line}-${s.code}`}>Line {s.line}, <code>{s.code}</code>: {s.reason}</li>)}
      </ul>
    </details>
  )
}

function ImportSectionsCard({ termId }: { termId: string }) {
  const run = useImportSections(termId)
  const result: SectionsImport | undefined = run.data
  const matched = result ? Object.entries(result.matched) : []
  return (
    <Card className="mb-4">
      <Card.Body>
        <FilePicker
          id="loader-file"
          label="Course loader file"
          pending={run.isPending}
          onFile={(text) => run.mutate(text)}
          help={<>The Alma/Leganto course loader layout (CSV or tab-separated), with <code>CourseID</code> as the live shell code. Importing again updates sections and keeps your decisions.</>}
        />
        {run.isError && <Alert variant="danger" className="small mt-3 mb-0">{apiErrorMessage(run.error, 'The file could not be imported.')}</Alert>}
        {result && (
          <Alert variant="success" className="small mt-3 mb-0" role="status">
            {result.added} section{result.added === 1 ? '' : 's'} added, {result.updated} updated.{' '}
            {matched.length > 0 && <>Matched: {matched.map(([k, n]) => `${n} ${SOURCE_LABELS[k as MatchSource].toLowerCase()}`).join(', ')}. </>}
            {result.needs_source} need a source.
            <SkippedList skipped={result.skipped} />
          </Alert>
        )}
      </Card.Body>
    </Card>
  )
}

function ImportPrimariesCard() {
  const run = useImportPrimaries()
  const result: PrimariesImport | undefined = run.data
  return (
    <Card className="mb-4">
      <Card.Header className="bg-white">
        <Card.Title as="h2" className="h6 mb-0">Primary shells</Card.Title>
      </Card.Header>
      <Card.Body>
        <FilePicker
          id="primaries-file"
          label="List of primary shells"
          pending={run.isPending}
          onFile={(text) => run.mutate(text)}
          help={<>An LMS export with a <code>Code</code> column (and optionally <code>Name</code>, <code>Org Unit Id</code>, <code>Department</code>), or one code per line. Codes that don’t fit your primary pattern are skipped. Then use <em>Match again</em>.</>}
        />
        {run.isError && <Alert variant="danger" className="small mt-3 mb-0">{apiErrorMessage(run.error, 'The file could not be imported.')}</Alert>}
        {result && (
          <Alert variant="success" className="small mt-3 mb-0" role="status">
            {result.added} primar{result.added === 1 ? 'y' : 'ies'} added, {result.updated} updated.
            <SkippedList skipped={result.skipped} />
          </Alert>
        )}
      </Card.Body>
    </Card>
  )
}

const lengthsToText = (lengths: Record<string, string>) =>
  Object.entries(lengths).map(([k, v]) => `${k} = ${v}`).join('\n')

const textToLengths = (text: string) =>
  Object.fromEntries(
    text
      .split('\n')
      .map((line) => line.split('=').map((s) => s.trim()))
      .filter((parts) => parts.length === 2 && parts[0] && parts[1]),
  )

function SettingsCard() {
  const settings = useRolloverSettings()
  if (!settings.data) {
    return settings.isError ? <Alert variant="danger">{apiErrorMessage(settings.error, 'Settings could not be loaded.')}</Alert> : null
  }
  return <SettingsForm key={JSON.stringify(settings.data)} saved={settings.data} />
}

function SettingsForm({ saved }: { saved: RolloverSettings }) {
  const save = useSaveRolloverSettings()
  const tryIt = useTryPrimaryPattern()
  const [pattern, setPattern] = useState(saved.primary_code_pattern ?? '')
  const [courseColumn, setCourseColumn] = useState(saved.course_column)
  const [partColumn, setPartColumn] = useState(saved.part_of_term_column)
  const [lengths, setLengths] = useState(lengthsToText(saved.lengths))
  const [sample, setSample] = useState('')

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate({
      primary_code_pattern: pattern.trim() || null,
      course_column: courseColumn,
      part_of_term_column: partColumn,
      lengths: textToLengths(lengths),
    })
  }
  const tried = tryIt.data

  return (
    <Card className="mb-4">
      <Card.Header className="bg-white">
        <Card.Title as="h2" className="h6 mb-0">How Stacks reads your files</Card.Title>
        <div className="small text-body-secondary mt-1">
          Live shells are read with the pattern under Terms
          {saved.section_code_pattern ? <> (<code>{saved.section_code_pattern}</code>)</> : ' (not set yet)'}.
        </div>
      </Card.Header>
      <Card.Body>
        <Form onSubmit={submit}>
          <Form.Group controlId="primary-pattern" className="mb-3">
            <FieldLabel>Primary shell codes</FieldLabel>
            <Form.Control
              className="font-monospace"
              value={pattern}
              onChange={(e) => { setPattern(e.target.value); tryIt.reset() }}
              placeholder="{subject}{number}_{mode}_{length}_PRIMARY"
            />
            <Form.Text>
              Use <code>{'{subject}'}</code> and <code>{'{number}'}</code>, and optionally <code>{'{mode}'}</code> (e.g. F2F, OL)
              and <code>{'{length}'}</code> (e.g. SEM, TER).
            </Form.Text>
          </Form.Group>
          <div className="d-flex gap-2 mb-3" style={{ maxWidth: 480 }}>
            <Form.Control size="sm" value={sample} onChange={(e) => setSample(e.target.value)} placeholder="GEO101_OL_TER_PRIMARY" aria-label="Try a primary code" />
            <Button
              size="sm"
              variant="outline-primary"
              disabled={!sample.trim() || !pattern.trim() || tryIt.isPending}
              onClick={() => tryIt.mutate({ primary_code_pattern: pattern.trim(), code: sample.trim() })}
            >
              Try
            </Button>
          </div>
          {tried && (
            <div className="small mb-3" role="status">
              {tried.error ? <span className="text-danger">{tried.error}</span>
                : tried.matches ? <>Course <code>{tried.course}</code>{tried.mode && <> · mode <code>{tried.mode}</code></>}{tried.length && <> · length <code>{tried.length}</code></>}</>
                : 'Doesn’t match the pattern.'}
            </div>
          )}
          <Row className="g-3 mb-3">
            <Col sm={6}>
              <Form.Group controlId="course-column">
                <FieldLabel>Course column</FieldLabel>
                <Form.Control value={courseColumn} onChange={(e) => setCourseColumn(e.target.value)} />
                <Form.Text>Holds subject and number, e.g. <code>GEO 101</code>.</Form.Text>
              </Form.Group>
            </Col>
            <Col sm={6}>
              <Form.Group controlId="part-column">
                <FieldLabel>Part-of-term column</FieldLabel>
                <Form.Control value={partColumn} onChange={(e) => setPartColumn(e.target.value)} />
              </Form.Group>
            </Col>
          </Row>
          <Form.Group controlId="lengths" className="mb-3">
            <FieldLabel>Part of term → length</FieldLabel>
            <Form.Control as="textarea" rows={4} className="font-monospace" value={lengths} onChange={(e) => setLengths(e.target.value)} placeholder={'FULL = SEM\nPT1 = TER'} />
            <Form.Text>One per line. Lengths must match the <code>{'{length}'}</code> part of primary codes.</Form.Text>
          </Form.Group>
          {save.isError && <Alert variant="danger" className="small">{apiErrorMessage(save.error, 'Settings could not be saved.')}</Alert>}
          {save.isSuccess && <Alert variant="success" className="small">Saved. Use <em>Match again</em> to apply them to imported sections.</Alert>}
          <Button type="submit" disabled={save.isPending}>Save</Button>
        </Form>
      </Card.Body>
    </Card>
  )
}

function RememberedCard() {
  const remembered = useRemembered()
  const forget = useForget()
  if (!remembered.data?.length) return null
  return (
    <Card>
      <Card.Header className="bg-white">
        <Card.Title as="h2" className="h6 mb-0">Remembered choices</Card.Title>
        <div className="small text-body-secondary mt-1">Primaries you chose, used for the same course and length in later terms.</div>
      </Card.Header>
      <Table responsive className="mb-0 align-middle">
        <thead>
          <tr>
            <th scope="col">Course</th>
            <th scope="col">Length</th>
            <th scope="col">Primary</th>
            <th scope="col"><span className="visually-hidden">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {remembered.data.map((r) => (
            <tr key={r.id}>
              <td>{r.course}</td>
              <td className="small">{r.length || 'Any'}</td>
              <td><code className="small">{r.primary}</code></td>
              <td className="text-end">
                <Button size="sm" variant="outline-danger" onClick={() => forget.mutate(r.id)} disabled={forget.isPending} aria-label={`Forget ${r.course} ${r.length}`}>
                  Forget
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}
