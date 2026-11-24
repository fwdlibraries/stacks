import { useState, type KeyboardEvent } from 'react'
import { Alert, Button, Form, InputGroup, ListGroup, Spinner } from 'react-bootstrap'
import { MagnifyingGlass } from '@phosphor-icons/react'
import { useLibrarySearch, type LookupCandidate } from '@/api/hooks/useIngest'
import { apiErrorMessage } from '@/lib/apiError'
import { CandidateItem } from '@/components/citations/CitationLookup'

interface LibrarySearchProps {
  onAdd: (candidate: LookupCandidate) => void
  isAdding: boolean
  addError?: string | null
}

/**
 * Keyword search of the library's discovery system (Primo). Catalogue results are
 * added bound to the library record; articles from the discovery index are added
 * as editable citations. Lives inside the citation form: Enter searches.
 */
export function LibrarySearch({ onAdd, isAdding, addError }: LibrarySearchProps) {
  const [text, setText] = useState('')
  const [query, setQuery] = useState('')
  const search = useLibrarySearch(query)
  const candidates = search.data?.pages.flatMap((page) => page.candidates) ?? []
  const total = search.data?.pages[0]?.total ?? 0

  const run = () => setQuery(text.trim())
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      run()
    }
  }

  return (
    <section aria-label="Search the library">
      <InputGroup>
        <Form.Control
          aria-label="Search the library"
          placeholder="Title, author, keywords"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <Button variant="outline-primary" onClick={run} disabled={!text.trim() || search.isFetching}>
          <MagnifyingGlass aria-hidden="true" /> Search
        </Button>
      </InputGroup>
      <Form.Text>Searches your library's catalogue and article index.</Form.Text>

      {search.isLoading && (
        <div className="text-center my-3">
          <Spinner animation="border" size="sm" role="status">
            <span className="visually-hidden">Searching…</span>
          </Spinner>
        </div>
      )}
      {search.isError && (
        <Alert variant="danger" className="small mt-2 mb-0">
          {apiErrorMessage(search.error, 'The search failed. Try again, or look the item up by identifier.')}
        </Alert>
      )}
      {search.isSuccess && candidates.length === 0 && (
        <p className="small text-body-secondary mt-2 mb-0">No results. Try other words, or enter the details yourself.</p>
      )}

      {candidates.length > 0 && (
        <>
          <p className="small text-body-secondary mt-2 mb-1" aria-live="polite">
            {total.toLocaleString()} {total === 1 ? 'result' : 'results'}
          </p>
          <ListGroup aria-label="Search results" style={{ maxHeight: '22rem', overflowY: 'auto' }}>
            {candidates.map((candidate) => (
              <CandidateItem
                key={`${candidate.source_system}:${candidate.source_identifier}`}
                candidate={candidate}
                isAdding={isAdding}
                onAdd={() => onAdd(candidate)}
              />
            ))}
          </ListGroup>
          {search.hasNextPage && (
            <Button
              variant="link"
              size="sm"
              className="mt-1 px-0"
              onClick={() => search.fetchNextPage()}
              disabled={search.isFetchingNextPage}
            >
              {search.isFetchingNextPage ? 'Loading…' : 'Show more results'}
            </Button>
          )}
        </>
      )}
      {addError && (
        <Alert variant="danger" className="small mt-2 mb-0">
          {addError}
        </Alert>
      )}
    </section>
  )
}

export default LibrarySearch
