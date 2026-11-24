import { useCitationHistory, type CitationEvent } from '@/api/hooks/useLinks'

const FIELD_LABELS: Record<string, string> = {
  resource_type: 'type',
  place_of_publication: 'place',
  isbn: 'ISBN',
  issn: 'ISSN',
  doi: 'DOI',
  url: 'URL',
  metadata: 'other details',
}

const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })

function describe(event: CitationEvent): string {
  switch (event.kind) {
    case 'updated': {
      const fields = Object.keys(event.details).map((f) => FIELD_LABELS[f] ?? f.replace(/_/g, ' '))
      return `Updated from the catalogue: ${fields.join(', ')}`
    }
    case 'missing':
      return 'Record removed from the catalogue'
    case 'suppressed':
      return 'Record hidden in the catalogue'
    case 'restored':
      return 'Record available in the catalogue again'
    default:
      return event.kind
  }
}

/** When a bound citation was last checked, and what the catalogue sync changed */
export function SyncHistory({ citationId, syncedAt }: { citationId: string; syncedAt?: string | null }) {
  const history = useCitationHistory(citationId)
  const events = history.data ?? []

  return (
    <div className="small text-body-secondary mb-3">
      <p className="mb-1">
        {syncedAt ? `Last checked against the catalogue on ${formatDate(syncedAt)}.` : 'Not checked against the catalogue yet.'}
      </p>
      {events.length > 0 && (
        <ul className="mb-0 ps-3" aria-label="Catalogue changes">
          {events.slice(0, 5).map((event, i) => (
            <li key={`${event.occurred_at}-${i}`}>
              {formatDate(event.occurred_at)}: {describe(event)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default SyncHistory
