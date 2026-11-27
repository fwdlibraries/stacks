import { logoUrl, useTenant } from '@/api/hooks/useTenant'
import { useParams } from 'react-router-dom'
import { Alert, Card, Col, Container, Nav, Row, Spinner } from 'react-bootstrap'
import { usePublicList } from '@/api/hooks/useLists'
import { CitationCard } from '@/components/citations/CitationCard'

/**
 * Public reading list view — unauthenticated, no editor controls.
 * This is what students see when they click through from the LMS.
 *
 * Performance notes:
 * - This component is the lightweight entry point (public.html)
 * - No WebSocket connection
 * - No auth state
 * - Statically cacheable — reading lists change infrequently mid-semester
 */
export default function PublicListView() {
  const tenant = useTenant()
  const logo = logoUrl(tenant.data)
  const { orgSlug, courseCode, term } = useParams<{
    orgSlug: string
    courseCode: string
    term: string
  }>()

  const { data: list, isLoading, isError } = usePublicList(
    orgSlug ?? '',
    courseCode ?? '',
    term ?? ''
  )

  if (isLoading) {
    return (
      <Container className="py-5 text-center">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading reading list...</span>
        </Spinner>
      </Container>
    )
  }

  if (isError || !list) {
    return (
      <Container className="py-5">
        <Alert variant="warning">
          Reading list not found. Please contact your instructor or librarian.
        </Alert>
      </Container>
    )
  }

  if (!list.is_published) {
    return (
      <Container className="py-5">
        <Alert variant="info">
          This reading list has not been published yet. Check back later.
        </Alert>
      </Container>
    )
  }

  const readings = list.sections.reduce((n, s) => n + s.citations.length, 0)
  const updated = list.updated_at
    ? new Date(list.updated_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    : null

  return (
    <div className="d-flex flex-column min-vh-100">
      {/* The organization's logo, if it has one */}
      {logo && (
        <header className="bg-white border-bottom">
          <Container className="py-3" style={{ maxWidth: '1120px' }}>
            <img src={logo} alt={tenant.data?.name ?? ''} style={{ maxHeight: '40px', maxWidth: '240px' }} />
          </Container>
        </header>
      )}

      {/* List header */}
      <div className="bg-white border-bottom">
        <Container className="py-4 py-md-5" style={{ maxWidth: '1120px' }}>
          <div className="small text-body-secondary mb-2">
            <span className="fw-semibold text-body">{courseCode}</span>
            {term && <> · {formatTerm(term)}</>} · Reading list
          </div>
          <h1 className="mb-0">{list.title}</h1>
          {list.description && (
            <p className="text-body-secondary mt-2 mb-0" style={{ maxWidth: '68ch' }}>{list.description}</p>
          )}
          <div className="d-flex flex-wrap gap-3 mt-3 small text-body-secondary">
            <span><strong className="text-body">{readings}</strong> {readings === 1 ? 'reading' : 'readings'}</span>
            <span><strong className="text-body">{list.sections.length}</strong> {list.sections.length === 1 ? 'section' : 'sections'}</span>
            {updated && <span>Updated {updated}</span>}
          </div>
        </Container>
      </div>

      <Container className="py-4 flex-grow-1" style={{ maxWidth: '1120px' }}>
        {list.sections.length === 0 ? (
          <p className="text-body-secondary">No items have been added to this reading list yet.</p>
        ) : (
          <Row className="g-4 flex-lg-row-reverse">
            {/* Section index: beside the list on wide screens, above it on phones */}
            {list.sections.length > 1 && (
              <Col lg={3}>
                <Card className="stacks-toc">
                  <Card.Body>
                    <h2 className="text-caps text-body-secondary mb-2">On this list</h2>
                    <Nav as="nav" aria-label="Sections" className="flex-column">
                      {list.sections.map((section) => (
                        <Nav.Link key={section.id} href={`#section-${section.id}`}>
                          <span>{section.title}</span>
                          <span className="text-body-secondary tabular-nums">{section.citations.length}</span>
                        </Nav.Link>
                      ))}
                    </Nav>
                  </Card.Body>
                </Card>
              </Col>
            )}

            <Col lg={list.sections.length > 1 ? 9 : 12}>
              {list.sections.map((section) => (
                <section key={section.id} id={`section-${section.id}`} aria-labelledby={`section-${section.id}-title`} className="mb-5">
                  <h2 id={`section-${section.id}-title`} className="h3 mb-1">{section.title}</h2>
                  {section.description && (
                    <p className="text-body-secondary small mb-3">{section.description}</p>
                  )}

                  {section.citations.length === 0 && (
                    <p className="text-body-secondary small">No items in this section.</p>
                  )}

                  {section.citations.map((citation) => (
                    <CitationCard
                      key={citation.id}
                      citation={citation}
                      displayMode="structured"
                    />
                  ))}
                </section>
              ))}
            </Col>
          </Row>
        )}

        <footer className="mt-4 pt-3 border-top text-body-secondary small">
          Powered by{' '}
          <a href="https://github.com/fwdlibraries/stacks" target="_blank" rel="noopener noreferrer">
            Stacks
          </a>
        </footer>
      </Container>
    </div>
  )
}

/** "fall-2026" → "Fall 2026" */
function formatTerm(term: string) {
  return term
    .split(/[-_]/)
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ')
}
