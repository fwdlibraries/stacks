import { useMemo, useState, type ChangeEvent } from 'react'
import { Alert, Badge, Button, Form, Modal, ProgressBar, Spinner, Table } from 'react-bootstrap'
import { SOURCE_LABELS } from '@/api/hooks/useIngest'
import type { ListSection } from '@/api/hooks/useLists'
import {
  useAddImport,
  useImportJob,
  useStartImport,
  type ImportItem,
  type ImportJob,
  type ItemChoice,
} from '@/api/hooks/useImports'
import { apiErrorMessage } from '@/lib/apiError'
import { FieldLabel } from '@/components/common/FormModal'

interface BulkImportModalProps {
  listId: string
  sections: ListSection[]
  defaultSectionId?: string
  onDone: (summary: string) => void
  onCancel: () => void
}

const MAX_FILE_BYTES = 1_000_000

/** Select value per row: "match:<index>", "as_entered" or "skip" */
type RowChoice = string

function defaultChoice(item: ImportItem, goodMatch: number): RowChoice {
  if (item.candidates.length && item.candidates[0].confidence >= goodMatch) return 'match:0'
  return 'as_entered'
}

function rowStatus(item: ImportItem, goodMatch: number): 'matched' | 'possible' | 'none' {
  const best = item.candidates[0]?.confidence ?? 0
  if (best >= goodMatch) return 'matched'
  return item.candidates.length ? 'possible' : 'none'
}

const describe = (item: ImportItem) =>
  item.entry.title ? [item.entry.title, item.entry.author[0], item.entry.year].filter(Boolean).join(' · ') : item.text

/**
 * Bulk import: paste a bibliography or upload RIS / BibTeX, let Stacks match each
 * entry to the library's records (or Crossref), review, and add to a section.
 */
export function BulkImportModal({ listId, sections, defaultSectionId, onDone, onCancel }: BulkImportModalProps) {
  const [text, setText] = useState('')
  const [sectionId, setSectionId] = useState(defaultSectionId ?? sections[0]?.id ?? '')
  const [fileError, setFileError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [choices, setChoices] = useState<Record<string, RowChoice>>({})

  const start = useStartImport(listId)
  const job = useImportJob(jobId)
  const add = useAddImport()
  const data = job.data

  const readFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    setFileError(null)
    if (!file) return
    if (file.size > MAX_FILE_BYTES) {
      setFileError('That file is too large (1 MB at most).')
      return
    }
    file.text().then(setText, () => setFileError('That file could not be read.'))
  }

  const submit = () =>
    start.mutate({ text, section_id: sectionId }, { onSuccess: (created) => setJobId(created.id) })

  const choiceFor = (item: ImportItem, current: ImportJob) => choices[item.id] ?? defaultChoice(item, current.good_match)

  const addAll = (current: ImportJob) => {
    const items: ItemChoice[] = current.items.map((item) => {
      const value = choiceFor(item, current)
      return value.startsWith('match:')
        ? { id: item.id, choice: 'match', candidate_index: Number(value.slice(6)) }
        : { id: item.id, choice: value as 'as_entered' | 'skip' }
    })
    add.mutate(
      { jobId: current.id, items },
      {
        onSuccess: (result) =>
          onDone(
            `Added ${result.added} ${result.added === 1 ? 'citation' : 'citations'}` +
              (result.skipped ? `, skipped ${result.skipped}` : '') +
              (result.failed.length ? `; ${result.failed.length} couldn't be added` : '') +
              '.'
          ),
      }
    )
  }

  const counts = useMemo(() => {
    const c = { matched: 0, possible: 0, none: 0 }
    data?.items.forEach((item) => (c[rowStatus(item, data.good_match)] += 1))
    return c
  }, [data])

  const reviewing = data?.status === 'awaiting_review'
  const adding = reviewing
    ? data.items.filter((item) => choiceFor(item, data) !== 'skip').length
    : 0

  return (
    <Modal show onHide={onCancel} size="xl" backdrop="static" centered scrollable>
      <Modal.Header closeButton>
        <Modal.Title as="h2" className="h3">
          Import citations
        </Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {!jobId && (
          <>
            <Form.Group className="mb-3" controlId="import-text">
              <FieldLabel required>References</FieldLabel>
              <Form.Control
                as="textarea"
                rows={10}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={'Paste a bibliography (one reference per line or numbered), or RIS / BibTeX records'}
              />
              <Form.Text>Stacks finds each item in your library's catalogue where it can.</Form.Text>
            </Form.Group>
            <Form.Group className="mb-3" controlId="import-file">
              <Form.Label>Or upload a file</Form.Label>
              <Form.Control type="file" accept=".ris,.bib,.bibtex,.txt,text/plain" onChange={readFile} />
              <Form.Text>RIS (.ris), BibTeX (.bib) or plain text, from Zotero, EndNote, Mendeley and others.</Form.Text>
              {fileError && <div className="text-danger small mt-1">{fileError}</div>}
            </Form.Group>
            <Form.Group className="mb-3" controlId="import-section" style={{ maxWidth: '24rem' }}>
              <FieldLabel required>Add to section</FieldLabel>
              <Form.Select value={sectionId} onChange={(e) => setSectionId(e.target.value)}>
                {sections.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </Form.Select>
            </Form.Group>
            {start.isError && (
              <Alert variant="danger" className="small mb-0">
                {apiErrorMessage(start.error, 'The import could not be started.')}
              </Alert>
            )}
          </>
        )}

        {jobId && (!data || data.status === 'queued' || data.status === 'processing') && (
          <div className="py-4">
            <p className="mb-2" aria-live="polite">
              Finding matches… {data ? `${data.matched} of ${data.total}` : ''}
            </p>
            <ProgressBar now={data && data.total ? (100 * data.matched) / data.total : 0} animated />
          </div>
        )}

        {data?.status === 'failed' && (
          <Alert variant="danger">Matching failed{data.error ? `: ${data.error}` : ''}. Try the import again.</Alert>
        )}

        {reviewing && (
          <>
            <p className="mb-2">
              <Badge bg="success" className="me-1">{counts.matched}</Badge> matched{' '}
              <Badge bg="warning" text="dark" className="ms-2 me-1">{counts.possible}</Badge> possible matches to check{' '}
              <Badge bg="secondary" className="ms-2 me-1">{counts.none}</Badge> not found
            </p>
            <p className="small text-body-secondary">
              Matches from your library stay up to date with the catalogue. Choose “as entered” to add an item as
              written, or skip it.
            </p>
            <Table size="sm" responsive className="align-middle">
              <thead>
                <tr>
                  <th scope="col">Reference</th>
                  <th scope="col" style={{ width: '45%' }}>
                    Add as
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => {
                  const status = rowStatus(item, data.good_match)
                  return (
                    <tr key={item.id} className={status === 'possible' ? 'table-warning' : undefined}>
                      <td className="small">
                        {describe(item)}
                        {item.warnings.length > 0 && (
                          <div className="text-body-secondary">Some sources didn't answer: {item.warnings.join('; ')}</div>
                        )}
                      </td>
                      <td>
                        <Form.Select
                          size="sm"
                          aria-label={`Add “${describe(item).slice(0, 60)}” as`}
                          value={choiceFor(item, data)}
                          onChange={(e) => setChoices((c) => ({ ...c, [item.id]: e.target.value }))}
                        >
                          {item.candidates.map((candidate, i) => (
                            <option key={`${candidate.source_system}:${candidate.source_identifier}`} value={`match:${i}`}>
                              {SOURCE_LABELS[candidate.source_system] ?? candidate.source_system}:{' '}
                              {(candidate.citation.title ?? 'Untitled').slice(0, 70)}
                              {candidate.citation.year ? ` (${candidate.citation.year})` : ''} ·{' '}
                              {Math.round(candidate.confidence * 100)}% match
                            </option>
                          ))}
                          <option value="as_entered">As entered</option>
                          <option value="skip">Skip</option>
                        </Form.Select>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
            {add.isError && (
              <Alert variant="danger" className="small mb-0">
                {apiErrorMessage(add.error, 'The citations could not be added.')}
              </Alert>
            )}
          </>
        )}
      </Modal.Body>
      <Modal.Footer>
        <Button variant="outline-secondary" onClick={onCancel} disabled={add.isPending}>
          Cancel
        </Button>
        {!jobId && (
          <Button onClick={submit} disabled={!text.trim() || !sectionId || start.isPending}>
            {start.isPending ? 'Reading…' : 'Find matches'}
          </Button>
        )}
        {reviewing && (
          <Button onClick={() => addAll(data)} disabled={add.isPending || adding === 0}>
            {add.isPending ? (
              <Spinner animation="border" size="sm" role="status">
                <span className="visually-hidden">Adding…</span>
              </Spinner>
            ) : (
              `Add ${adding} ${adding === 1 ? 'citation' : 'citations'}`
            )}
          </Button>
        )}
      </Modal.Footer>
    </Modal>
  )
}

export default BulkImportModal
