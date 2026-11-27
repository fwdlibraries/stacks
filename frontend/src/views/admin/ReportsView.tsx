import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Badge, Button, Card, Col, Row, Spinner, Table } from 'react-bootstrap'
import { useReports, useSyncNow, type Reports } from '@/api/hooks/useAdmin'
import { apiErrorMessage } from '@/lib/apiError'
import { NEEDS_ATTENTION } from '@/lib/sourceStatus'

const formatDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—'

function Stat({ value, label, note }: { value: string | number; label: string; note?: string }) {
  return (
    <Card className="h-100 stacks-stat">
      <Card.Body>
        <div className="text-caps text-body-secondary">{label}</div>
        <div className="stacks-stat-value mt-1">{typeof value === 'number' ? value.toLocaleString() : value}</div>
        {note && <div className="small text-body-secondary">{note}</div>}
      </Card.Body>
    </Card>
  )
}

/** A titled panel; tables inside run edge to edge. */
function Panel({ title, intro, children, className }: { title: string; intro?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <Card.Header className="bg-white">
        <Card.Title as="h2" className="h6 mb-0">{title}</Card.Title>
        {intro && <div className="small text-body-secondary mt-1">{intro}</div>}
      </Card.Header>
      {children}
    </Card>
  )
}

const empty = (text: string) => <Card.Body className="text-body-secondary small">{text}</Card.Body>

const listLink = (id: string, title: string) => <Link to={`/lists/${id}`}>{title}</Link>

export default function ReportsView() {
  const reports = useReports()
  if (reports.isLoading) return <Spinner animation="border" role="status"><span className="visually-hidden">Loading…</span></Spinner>
  if (reports.isError || !reports.data) return <Alert variant="danger">{apiErrorMessage(reports.error, 'Reports could not be loaded.')}</Alert>
  const r = reports.data
  const o = r.overview
  const direct = o.clicks ? Math.round((100 * o.direct_clicks) / o.clicks) : null

  return (
    <>
      <p className="text-body-secondary mt-n2 mb-4">For the reading lists you can see reports for. Clicks are counted without recording who clicked.</p>
      <Row className="g-3 mb-4">
        <Col sm={6} lg={3}><Stat value={o.lists_published} label="Published lists" note={`${o.lists_draft} drafts`} /></Col>
        <Col sm={6} lg={3}><Stat value={o.citations} label="Citations" note={`${o.library_records} library records`} /></Col>
        <Col sm={6} lg={3}><Stat value={o.clicks} label={`Student clicks, last ${r.window_days} days`} note={direct === null ? undefined : `${direct}% went straight to the resource`} /></Col>
        <Col sm={6} lg={3}><Stat value={o.flagged} label="Need attention" note="Removed or hidden in the catalogue" /></Col>
      </Row>

      <SyncCard sync={r.sync} />

      <Panel title="Need attention" intro="Flagged by the catalogue sync." className="mt-4">
      {r.flagged.length === 0 ? (
        empty('Nothing flagged by the catalogue sync.')
      ) : (
        <Table responsive className="mb-0">
          <thead><tr><th scope="col">Citation</th><th scope="col">List</th><th scope="col">Problem</th><th scope="col">Since</th></tr></thead>
          <tbody>
            {r.flagged.map((f) => (
              <tr key={f.citation_id}>
                <td>{f.title}</td>
                <td>{listLink(f.list_id, f.list_title)} › {f.section_title}</td>
                <td><Badge bg="warning" text="dark">{NEEDS_ATTENTION[f.status]?.badge ?? f.status}</Badge></td>
                <td className="small">{formatDate(f.since)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      </Panel>

      <Panel
        title="Hard to reach"
        className="mt-4"
        intro={<>
          Clicked in the last {r.window_days} days, but mostly couldn’t go straight to the full text: students landed on a
          catalogue page, the DOI or a menu instead. Open the citation and use <em>Check link</em> to see why.
        </>}
      >
      {r.hard_to_reach.length === 0 ? (
        empty('None.')
      ) : (
        <Table responsive className="mb-0">
          <thead><tr><th scope="col">Citation</th><th scope="col">List</th><th scope="col" className="text-end">Clicks</th><th scope="col" className="text-end">Not direct</th></tr></thead>
          <tbody>
            {r.hard_to_reach.map((h) => (
              <tr key={h.citation_id}>
                <td>{h.title}</td>
                <td>{listLink(h.list_id, h.list_title)} › {h.section_title}</td>
                <td className="text-end tabular-nums">{h.clicks}</td>
                <td className="text-end tabular-nums">{h.fallback_clicks}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      </Panel>

      <Row className="mt-4 g-3">
        <Col md={6}>
          <Panel title="Most used lists" className="h-100">
          {r.top_lists.length === 0 ? empty('No clicks yet.') : (
            <Table className="mb-0"><tbody>
              {r.top_lists.map((t) => <tr key={t.list_id}><td>{listLink(t.list_id, t.list_title)}</td><td className="text-end tabular-nums">{t.clicks}</td></tr>)}
            </tbody></Table>
          )}
          </Panel>
        </Col>
        <Col md={6}>
          <Panel title="Most used citations" className="h-100">
          {r.top_citations.length === 0 ? empty('No clicks yet.') : (
            <Table className="mb-0"><tbody>
              {r.top_citations.map((t) => <tr key={t.citation_id}><td>{t.title}<div className="small text-body-secondary">{t.list_title}</div></td><td className="text-end tabular-nums">{t.clicks}</td></tr>)}
            </tbody></Table>
          )}
          </Panel>
        </Col>
      </Row>

      <Panel title="Recent imports" className="mt-4">
      {r.imports.length === 0 ? empty('None.') : (
        <Table responsive className="mb-0">
          <thead><tr><th scope="col">When</th><th scope="col">List</th><th scope="col">By</th><th scope="col" className="text-end">Entries</th><th scope="col" className="text-end">Added</th><th scope="col">Status</th></tr></thead>
          <tbody>
            {r.imports.map((i) => (
              <tr key={i.id}>
                <td className="small">{formatDate(i.created_at)}</td>
                <td>{i.list_id && i.list_title ? listLink(i.list_id, i.list_title) : '—'}</td>
                <td>{i.by ?? '—'}</td>
                <td className="text-end tabular-nums">{i.total}</td>
                <td className="text-end tabular-nums">{i.added ?? '—'}</td>
                <td><Badge bg={i.status === 'completed' ? 'success' : i.status === 'failed' ? 'danger' : 'secondary'}>{i.status.replace('_', ' ')}</Badge></td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      </Panel>
    </>
  )
}

function SyncCard({ sync }: { sync: Reports['sync'] }) {
  const run = useSyncNow()
  if (!sync.connected) {
    return <Alert variant="secondary" className="small">Catalogue sync starts once Alma is connected (Library connections).</Alert>
  }
  return (
    <Card>
      <Card.Body className="d-flex justify-content-between align-items-start gap-3 flex-wrap">
        <div className="d-flex gap-3 align-items-start">
        <span
          className={`stacks-dot mt-2 bg-${sync.last_status === 'failed' ? 'danger' : sync.last_run_at ? 'success' : 'secondary'}`}
          aria-hidden="true"
        />
        <div>
          <Card.Title as="h2" className="h6 mb-1">Catalogue sync</Card.Title>
          <div className="small">
            {sync.last_run_at ? (
              <>
                Last checked {formatDate(sync.last_run_at)}:{' '}
                {sync.last_status === 'failed' ? (
                  <span className="text-danger">failed{sync.error ? ` (${sync.error})` : ''}</span>
                ) : (
                  `${sync.checked ?? 0} records checked, ${sync.updated ?? 0} updated, ${sync.flagged ?? 0} newly flagged`
                )}
                .
              </>
            ) : (
              'Not run yet.'
            )}{' '}
            Runs every night.
          </div>
        </div>
        </div>
        {sync.can_run && (
          <div className="text-end">
            <Button size="sm" variant="outline-primary" onClick={() => run.mutate()} disabled={run.isPending || run.isSuccess}>
              {run.isSuccess ? 'Started' : 'Sync now'}
            </Button>
            {run.isSuccess && <div className="small text-body-secondary mt-1">Refresh in a minute for the result.</div>}
            {run.isError && <div className="small text-danger mt-1">{apiErrorMessage(run.error, 'Couldn’t start the sync.')}</div>}
          </div>
        )}
      </Card.Body>
    </Card>
  )
}
