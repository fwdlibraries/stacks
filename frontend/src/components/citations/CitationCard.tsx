import { Card, Badge, Button } from 'react-bootstrap'
import { resolveCitationLink, getLinkLabel } from '@/lib/citationLink'
import type { Citation } from '@/api/hooks/useLists'

/**
 * Citation display modes.
 * v0.1: 'structured' only.
 * Future: 'apa' | 'mla' | 'chicago' via citeproc-js integration.
 */
export type CitationDisplayMode = 'structured' | 'apa' | 'mla' | 'chicago'

interface CitationCardProps {
  citation: Citation
  displayMode?: CitationDisplayMode
  linkResolverBaseUrl?: string
  showStaffNote?: boolean
  onEdit?: (citation: Citation) => void
  onDelete?: (citationId: string) => void
  isDragging?: boolean
}

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  book: 'Book',
  book_chapter: 'Book Chapter',
  journal_article: 'Journal Article',
  ebook: 'eBook',
  av_media: 'AV / Media',
  website: 'Website',
  uploaded_file: 'File',
  other: 'Other',
}

const RESOURCE_TYPE_COLORS: Record<string, string> = {
  book: 'primary',
  book_chapter: 'info',
  journal_article: 'success',
  ebook: 'primary',
  av_media: 'warning',
  website: 'secondary',
  uploaded_file: 'danger',
  other: 'secondary',
}

export function CitationCard({
  citation,
  displayMode = 'structured',
  linkResolverBaseUrl,
  showStaffNote = false,
  onEdit,
  onDelete,
  isDragging = false,
}: CitationCardProps) {
  const resolver = linkResolverBaseUrl ? { base_url: linkResolverBaseUrl } : null
  const link = resolveCitationLink(citation, resolver)
  const linkLabel = getLinkLabel(citation)

  return (
    <Card
      className={`mb-2 ${isDragging ? 'opacity-50 shadow-lg' : ''}`}
      style={{ cursor: onEdit ? 'default' : 'auto' }}
    >
      <Card.Body>
        <div className="d-flex align-items-start justify-content-between gap-2">
          <div className="flex-grow-1">
            {/* Resource type badge */}
            <Badge
              bg={RESOURCE_TYPE_COLORS[citation.resource_type] ?? 'secondary'}
              className="me-2 mb-1"
              style={{ fontSize: '0.7rem' }}
            >
              {RESOURCE_TYPE_LABELS[citation.resource_type] ?? citation.resource_type}
            </Badge>

            {!citation.is_required && (
              <Badge bg="light" text="dark" className="me-2 mb-1" style={{ fontSize: '0.7rem' }}>
                Optional
              </Badge>
            )}

            {/* Title */}
            <Card.Title className="mb-1" style={{ fontSize: '1rem' }}>
              {link ? (
                <a href={link} target="_blank" rel="noopener noreferrer">
                  {citation.title}
                </a>
              ) : (
                citation.title
              )}
            </Card.Title>

            {/* Structured metadata display (v0.1) */}
            {displayMode === 'structured' && (
              <StructuredCitationMeta citation={citation} />
            )}

            {/* Student-facing note */}
            {citation.student_note && (
              <p className="text-muted mt-2 mb-0" style={{ fontSize: '0.875rem' }}>
                <em>{citation.student_note}</em>
              </p>
            )}

            {/* Staff note (editor view only) */}
            {showStaffNote && citation.staff_note && (
              <p className="text-warning mt-1 mb-0" style={{ fontSize: '0.8rem' }}>
                <strong>Staff note:</strong> {citation.staff_note}
              </p>
            )}
          </div>

          {/* Action buttons (editor view only) */}
          {(onEdit || onDelete) && (
            <div className="d-flex gap-1 flex-shrink-0">
              {onEdit && (
                <Button
                  variant="outline-secondary"
                  size="sm"
                  onClick={() => onEdit(citation)}
                  aria-label="Edit citation"
                >
                  Edit
                </Button>
              )}
              {onDelete && (
                <Button
                  variant="outline-danger"
                  size="sm"
                  onClick={() => onDelete(citation.id)}
                  aria-label="Delete citation"
                >
                  Delete
                </Button>
              )}
            </div>
          )}
        </div>

        {/* Link button */}
        {link && linkLabel && (
          <div className="mt-2">
            <Button
              variant="link"
              size="sm"
              href={link}
              target="_blank"
              rel="noopener noreferrer"
              className="p-0"
            >
              {linkLabel} →
            </Button>
          </div>
        )}
      </Card.Body>
    </Card>
  )
}

function StructuredCitationMeta({ citation }: { citation: Citation }) {
  const parts: string[] = []

  if (citation.author?.length) {
    parts.push(citation.author.join(', '))
  }
  if (citation.year) {
    parts.push(String(citation.year))
  }
  if (citation.publisher) {
    parts.push(citation.publisher)
  }
  if (citation.doi) {
    parts.push(`DOI: ${citation.doi}`)
  }

  if (!parts.length) return null

  return (
    <p className="text-muted mb-0" style={{ fontSize: '0.875rem' }}>
      {parts.join(' · ')}
    </p>
  )
}

export default CitationCard
