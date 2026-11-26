import { Link } from 'react-router-dom'
import { Alert, Badge, ListGroup, Spinner } from 'react-bootstrap'
import { Books } from '@phosphor-icons/react'
import { useReadingLists } from '@/api/hooks/useLists'
import { EmptyState } from '@/components/common/EmptyState'
import { termLabel } from '@/lib/listTerms'

export default function ListsIndexView() {
  const { data: lists, isLoading, isError } = useReadingLists()

  return (
    <>
      <h1 className="mb-4">Reading lists</h1>

      {isLoading && (
        <div className="text-center py-5">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading reading lists…</span>
          </Spinner>
        </div>
      )}

      {isError && (
        <Alert variant="warning">
          Reading lists could not be loaded. Check that the Stacks API is running.
        </Alert>
      )}

      {lists && lists.length === 0 && (
        <EmptyState icon={Books} heading="No reading lists yet">
          Reading lists are created when an instructor opens Stacks from a course in the LMS.
        </EmptyState>
      )}

      {lists && lists.length > 0 && (
        <ListGroup>
          {lists.map((list) => (
            <ListGroup.Item
              key={list.id}
              action
              as={Link}
              to={`/lists/${list.id}`}
              className="d-flex justify-content-between align-items-center py-3"
            >
              <span>
                {list.title}
                <span className="d-block small text-body-secondary">{termLabel(list)}</span>
              </span>
              <Badge bg={list.is_published ? 'published' : 'secondary'}>
                {list.is_published ? 'Published' : 'Draft'}
              </Badge>
            </ListGroup.Item>
          ))}
        </ListGroup>
      )}
    </>
  )
}
