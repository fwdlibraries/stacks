import { Alert, Button, Spinner } from 'react-bootstrap'
import { Warning } from '@phosphor-icons/react'
import { useLinkCheck, type LinkCheckResult } from '@/api/hooks/useLinks'
import { apiErrorMessage } from '@/lib/apiError'

const STEP_LABELS: Record<string, string> = {
  libkey: 'LibKey',
  alma: 'Library link resolver',
  open_access: 'Open access',
  fallback: 'Standard link',
}

const FALLBACK_LABELS: Record<string, string> = {
  library_record: 'the catalogue record',
  full_text: 'the link resolver menu',
  doi: 'the DOI',
  web: 'its web address',
}

const OUTCOME_LABELS = { found: 'found', not_found: 'nothing found', error: 'failed', skipped: 'not set up' }

function summary(result: LinkCheckResult): string {
  if (!result.url) return 'Students have no link for this citation.'
  if (result.resolved_by === 'fallback') {
    return `No direct link found: students go to ${FALLBACK_LABELS[result.detail ?? ''] ?? 'a standard link'}.`
  }
  const via = STEP_LABELS[result.resolved_by ?? ''] ?? result.resolved_by
  return `Students go straight to ${result.detail ? `${result.detail} ` : 'the resource '}(via ${via}).`
}

/** "Where does this link go?" for the citation editor */
export function LinkCheck({ citationId }: { citationId: string }) {
  const check = useLinkCheck()
  const result = check.data

  return (
    <section aria-label="Link check" className="mb-3">
      <Button
        variant="outline-secondary"
        size="sm"
        onClick={() => check.mutate(citationId)}
        disabled={check.isPending}
      >
        {check.isPending ? (
          <>
            <Spinner animation="border" size="sm" role="status" className="me-1" />
            Checking…
          </>
        ) : (
          'Check link'
        )}
      </Button>
      {check.isError && (
        <Alert variant="danger" className="small mt-2 mb-0">
          {apiErrorMessage(check.error, 'The link could not be checked.')}
        </Alert>
      )}
      {result && (
        <div className="small mt-2" aria-live="polite">
          {result.retracted && (
            <Alert variant="warning" className="small d-flex gap-2 align-items-start py-2">
              <Warning aria-hidden="true" size={18} className="flex-shrink-0" />
              This article has been retracted. Students are shown the retraction notice.
            </Alert>
          )}
          <p className="mb-1">
            {summary(result)}{' '}
            {result.url && (
              <a href={result.url} target="_blank" rel="noopener noreferrer">
                Open
              </a>
            )}
          </p>
          <ol className="text-body-secondary mb-0 ps-3">
            {result.steps.map((step) => (
              <li key={step.step}>
                {STEP_LABELS[step.step] ?? step.step}: {OUTCOME_LABELS[step.outcome]}
                {step.outcome === 'found' && step.step !== 'fallback' && step.detail ? ` (${step.detail})` : ''}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  )
}

export default LinkCheck
