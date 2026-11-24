import { useParams } from 'react-router-dom'
import { Container, Alert, Spinner } from 'react-bootstrap'
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

  return (
    <Container className="py-4" style={{ maxWidth: '800px' }}>
      {/* List header */}
      <h1 className="h3 mb-1">{list.title}</h1>
      {list.description && (
        <p className="text-muted mb-3">{list.description}</p>
      )}

      <hr className="mb-4" />

      {/* Sections */}
      {list.sections.length === 0 && (
        <p className="text-muted">No items have been added to this reading list yet.</p>
      )}

      {list.sections.map((section) => (
        <div key={section.id} className="mb-4">
          <h2 className="h5 mb-1">{section.title}</h2>
          {section.description && (
            <p className="text-muted small mb-2">{section.description}</p>
          )}

          {section.citations.length === 0 && (
            <p className="text-muted small">No items in this section.</p>
          )}

          {section.citations.map((citation) => (
            <CitationCard
              key={citation.id}
              citation={citation}
              displayMode="structured"
            />
          ))}
        </div>
      ))}

      <footer className="mt-5 pt-3 border-top text-muted small">
        Powered by{' '}
        <a href="https://github.com/fwdlibraries/stacks" target="_blank" rel="noopener noreferrer">
          Stacks
        </a>
      </footer>
    </Container>
  )
}
