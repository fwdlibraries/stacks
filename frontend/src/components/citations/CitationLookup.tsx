import { useState, type KeyboardEvent } from 'react'
import { Alert, Badge, Button, Form, InputGroup, ListGroup, Spinner } from 'react-bootstrap'
import { Books, MagnifyingGlass } from '@phosphor-icons/react'
import { SOURCE_LABELS, useLookup, type LookupCandidate } from '@/api/hooks/useIngest'
import { apiErrorMessage } from '@/lib/apiError'

interface CitationLookupProps {
  onAdd: (candidate: LookupCandidate) => void
  isAdding: boolean
  addError?: string | null
}

/**
 * Find a record by DOI, ISBN or Alma MMS ID and add it. Lives inside the citation
 * form, so Enter here runs the lookup instead of submitting the form.
 */
export function CitationLookup({ onAdd, isAdding, addError }: CitationLookupProps) {
  const [query, setQuery] = useState('')
  const lookup = useLookup()
  const result = lookup.data

  const run = () => {
    if (query.trim()) lookup.mutate(query.trim())
  }
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      run()
    }
  }

  return (
    <section aria-labelledby="citation-lookup-heading" className="mb-4">
      <h3 id="citation-lookup-heading" className="h6">
        Look it up
      </h3>
      <InputGroup>
        <Form.Control
          aria-label="DOI, ISBN or MMS ID"
          placeholder="DOI, ISBN or Alma MMS ID"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <Button variant="outline-primary" onClick={run} disabled={lookup.isPending || !query.trim()}>
          {lookup.isPending ? (
            <Spinner animation="border" size="sm" role="status">
              <span className="visually-hidden">Looking up…</span>
            </Spinner>
          ) : (
            <>
              <MagnifyingGlass aria-hidden="true" /> Look up
            </>
          )}
        </Button>
      </InputGroup>
      <Form.Text>Paste an identifier, or a reference that contains one.</Form.Text>

      {lookup.isError && (
        <Alert variant="danger" className="small mt-2 mb-0">
          {apiErrorMessage(lookup.error, 'The lookup failed. Try again, or enter the details below.')}
        </Alert>
      )}
      {result?.warnings.map((warning) => (
        <Alert key={warning} variant="warning" className="small mt-2 mb-0">
          {warning}
        </Alert>
      ))}
      {result && result.identifiers.length === 0 && (
        <p className="small text-body-secondary mt-2 mb-0">
          No DOI, ISBN or MMS ID found in that text. Check it, or enter the details below.
        </p>
      )}
      {result && result.identifiers.length > 0 && result.candidates.length === 0 && (
        <p className="small text-body-secondary mt-2 mb-0">Nothing found for that. Enter the details below.</p>
      )}

      {result && result.candidates.length > 0 && (
        <ListGroup className="mt-2" aria-label="Lookup results">
          {result.candidates.map((candidate) => (
            <CandidateItem
              key={`${candidate.source_system}:${candidate.source_identifier}`}
              candidate={candidate}
              isAdding={isAdding}
              onAdd={() => onAdd(candidate)}
            />
          ))}
        </ListGroup>
      )}
      {addError && (
        <Alert variant="danger" className="small mt-2 mb-0">
          {addError}
        </Alert>
      )}
    </section>
  )
}

function CandidateItem({
  candidate,
  isAdding,
  onAdd,
}: {
  candidate: LookupCandidate
  isAdding: boolean
  onAdd: () => void
}) {
  const { citation } = candidate
  const details = [citation.author.join('; '), citation.year, citation.publisher, citation.edition]
    .filter(Boolean)
    .join(' · ')
  const title = citation.title ?? 'Untitled record'

  return (
    <ListGroup.Item className="d-flex align-items-start justify-content-between gap-3">
      <div>
        <Badge bg={candidate.authoritative ? 'primary' : 'secondary'} className="me-2">
          {candidate.authoritative && <Books aria-hidden="true" className="me-1" />}
          {SOURCE_LABELS[candidate.source_system] ?? candidate.source_system}
        </Badge>
        <strong>{title}</strong>
        {details && <div className="small text-body-secondary">{details}</div>}
        {candidate.authoritative && (
          <div className="small text-body-secondary">Stays up to date with your library's catalogue.</div>
        )}
      </div>
      <Button
        size="sm"
        variant="primary"
        className="flex-shrink-0"
        onClick={onAdd}
        disabled={isAdding || !citation.title}
        aria-label={`Add ${title}`}
      >
        Add
      </Button>
    </ListGroup.Item>
  )
}

export default CitationLookup
