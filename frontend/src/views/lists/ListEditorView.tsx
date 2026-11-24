import { Link, useParams } from 'react-router-dom'
import { Alert, Badge, Spinner } from 'react-bootstrap'
import { ListPlus } from '@phosphor-icons/react'
import { useReadingListFull } from '@/api/hooks/useLists'
import { CitationCard } from '@/components/citations/CitationCard'
import { EmptyState } from '@/components/common/EmptyState'

/**
 * Reading list editor. Scaffold only for now: renders the list read-only with
 * staff notes. Drag-and-drop (dnd-kit), citation editing, import and live
 * collaboration (lib/websocket.ts) will build on this view.
 */
export default function ListEditorView() {
  const { listId = '' } = useParams<{ listId: string }>()
  const { data: list, isLoading, isError } = useReadingListFull(listId)

  if (isLoading) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading reading list…</span>
        </Spinner>
      </div>
    )
  }

  if (isError || !list) {
    return (
      <Alert variant="warning">
        This reading list could not be loaded. <Link to="/lists">Back to reading lists</Link>
      </Alert>
    )
  }

  return (
    <div style={{ maxWidth: '800px' }}>
      <nav aria-label="breadcrumb" className="small mb-2">
        <Link to="/lists">Reading lists</Link>
      </nav>

      <div className="d-flex align-items-center gap-2 mb-1">
        <h1 className="mb-0">{list.title}</h1>
        <Badge bg={list.is_published ? 'published' : 'secondary'}>
          {list.is_published ? 'Published' : 'Draft'}
        </Badge>
      </div>
      {list.description && <p className="text-body-secondary">{list.description}</p>}

      <hr className="mb-4" />

      {list.sections.length === 0 && (
        <EmptyState icon={ListPlus} heading="No sections yet">
          Add a section such as “Required” or “Week 1”, then add citations to it.
        </EmptyState>
      )}

      {list.sections.map((section) => (
        <section key={section.id} className="mb-4">
          <h2 className="h3 mb-1">{section.title}</h2>
          {section.description && (
            <p className="text-body-secondary small mb-2">{section.description}</p>
          )}
          {section.citations.length === 0 && (
            <p className="text-body-secondary small">No citations in this section.</p>
          )}
          {section.citations.map((citation) => (
            <CitationCard key={citation.id} citation={citation} showStaffNote />
          ))}
        </section>
      ))}
    </div>
  )
}
