import { useState, type ReactNode } from 'react'
import { Alert, Button, Col, Form, Row, Tab, Tabs } from 'react-bootstrap'
import { Books } from '@phosphor-icons/react'
import { FieldLabel, FormModal } from '@/components/common/FormModal'
import { CitationLookup } from '@/components/citations/CitationLookup'
import { LibrarySearch } from '@/components/citations/LibrarySearch'
import type { Citation, CitationInput, ResourceType } from '@/api/hooks/useLists'
import { useIngestCapabilities, type LookupCandidate } from '@/api/hooks/useIngest'
import {
  RESOURCE_TYPE_OPTIONS,
  citationToForm,
  emptyCitationForm,
  fieldsFor,
  formToCitationInput,
  validateCitationForm,
  type CitationFormErrors,
  type CitationFormValues,
} from '@/lib/citationForm'

interface CitationFormModalProps {
  /** Existing citation to edit; omit to add a new one */
  citation?: Citation
  sectionTitle: string
  isPending: boolean
  error?: string | null
  onSubmit: (input: CitationInput) => void
  onCancel: () => void
  /** Adding: add a looked-up record, with the instructor fields filled in here */
  onAddFromSource?: (candidate: LookupCandidate, input: InstructorFields) => void
  isAddingFromSource?: boolean
  addFromSourceError?: string | null
  /** Editing a bound citation: detach it from the library record */
  onUnlink?: () => Promise<unknown>
  unlinkError?: string | null
}

/** What staff control on any citation, including one bound to a library record */
export type InstructorFields = Pick<CitationInput, 'is_required' | 'student_note' | 'staff_note'>

type AddTab = 'search' | 'lookup' | 'manual'

const INSTRUCTOR_KEYS = new Set<keyof CitationFormValues>(['is_required', 'student_note', 'staff_note'])

/** Mount with a `key` per citation so the fields reset when it changes. */
export function CitationFormModal({
  citation,
  sectionTitle,
  isPending,
  error,
  onSubmit,
  onCancel,
  onAddFromSource,
  isAddingFromSource = false,
  addFromSourceError,
  onUnlink,
  unlinkError,
}: CitationFormModalProps) {
  // Bound citations follow the library's record: only the instructor's fields are editable
  const [bound, setBound] = useState(Boolean(citation?.is_bound))
  const [unlinking, setUnlinking] = useState(false)
  // Adding: which way in. Defaults to library search when it's set up
  const [tab, setTab] = useState<AddTab>()
  const capabilities = useIngestCapabilities()
  const [values, setValues] = useState<CitationFormValues>(() =>
    citation ? citationToForm(citation) : emptyCitationForm()
  )
  const [errors, setErrors] = useState<CitationFormErrors>({})
  const show = fieldsFor(values.resource_type)
  // Uploads aren't supported yet, but an existing uploaded-file citation keeps its type
  const typeOptions =
    values.resource_type === 'uploaded_file'
      ? [...RESOURCE_TYPE_OPTIONS, { value: 'uploaded_file' as const, label: 'Uploaded file' }]
      : RESOURCE_TYPE_OPTIONS

  const set = <K extends keyof CitationFormValues>(key: K, value: CitationFormValues[K]) =>
    setValues((v) => ({ ...v, [key]: value }))

  const instructorFields = (): InstructorFields => ({
    is_required: values.is_required,
    student_note: values.student_note,
    staff_note: values.staff_note,
  })

  const unlink = async () => {
    if (!onUnlink) return
    setUnlinking(true)
    try {
      await onUnlink()
      setBound(false)
    } catch {
      // unlinkError shows the reason
    } finally {
      setUnlinking(false)
    }
  }

  const submit = () => {
    if (bound) {
      onSubmit(instructorFields())
      return
    }
    const found = validateCitationForm(values)
    setErrors(found)
    if (Object.keys(found).length === 0) onSubmit(formToCitationInput(values))
  }

  /** Text input with label above and error below, per the style guide */
  const field = (
    key: keyof CitationFormValues,
    label: string,
    options: { required?: boolean; help?: ReactNode; type?: string; as?: 'textarea'; rows?: number } = {}
  ) => (
    <Form.Group className="mb-3" controlId={`citation-${key}`}>
      <FieldLabel required={options.required}>{label}</FieldLabel>
      <Form.Control
        disabled={bound && !INSTRUCTOR_KEYS.has(key)}
        type={options.type ?? 'text'}
        as={options.as}
        rows={options.rows}
        value={values[key] as string}
        onChange={(e) => set(key, e.target.value as never)}
        isInvalid={Boolean(errors[key])}
      />
      {errors[key] && <Form.Control.Feedback type="invalid">{errors[key]}</Form.Control.Feedback>}
      {options.help && <Form.Text>{options.help}</Form.Text>}
    </Form.Group>
  )

  const bibliographicFields = (
    <>
      <Form.Group className="mb-3" controlId="citation-resource_type" style={{ maxWidth: '20rem' }}>
        <FieldLabel required>Resource type</FieldLabel>
        <Form.Select
          disabled={bound}
          value={values.resource_type}
          onChange={(e) => set('resource_type', e.target.value as ResourceType)}
        >
          {typeOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Form.Select>
      </Form.Group>

      {field('title', 'Title', { required: true })}
      {field('authors', 'Authors', {
        as: 'textarea',
        rows: 2,
        help: 'One per line, family name first: Carr, Edward Hallett',
      })}

      <Row>
        <Col md={3}>{field('year', 'Year', { type: 'text' })}</Col>
        <Col md={show.edition ? 6 : 9}>
          {field('publisher', values.resource_type === 'journal_article' ? 'Journal' : 'Publisher')}
        </Col>
        {show.edition && <Col md={3}>{field('edition', 'Edition')}</Col>}
      </Row>

      {show.journal && (
        <Row>
          <Col md={4}>{field('volume', 'Volume')}</Col>
          <Col md={4}>{field('issue', 'Issue')}</Col>
          <Col md={4}>{field('pages', 'Pages')}</Col>
        </Row>
      )}

      <Row>
        {show.isbn && <Col md={6}>{field('isbn', 'ISBN')}</Col>}
        <Col md={show.isbn ? 6 : 12}>{field('doi', 'DOI', { help: 'Links students to the DOI when set.' })}</Col>
      </Row>
      {field('url', 'URL', { type: 'url' })}
    </>
  )

  // Required and the notes apply however the citation is added, so they sit below the tabs
  const instructorSection = (
    <fieldset className="border-top pt-3">
      <legend className="h6">For students</legend>
      <Form.Check
        className="mb-3"
        id="citation-is_required"
        type="checkbox"
        label="Required reading"
        checked={values.is_required}
        onChange={(e) => set('is_required', e.target.checked)}
      />
      {field('student_note', 'Student note', {
        as: 'textarea',
        rows: 2,
        help: 'Shown to students, e.g. which chapters to read.',
      })}
      {field('staff_note', 'Staff note', {
        as: 'textarea',
        rows: 2,
        help: 'Only visible to instructors and library staff.',
      })}
    </fieldset>
  )

  const addFromSource = (candidate: LookupCandidate) => onAddFromSource?.(candidate, instructorFields())
  const adding = !citation && onAddFromSource
  const activeTab = tab ?? (capabilities.data?.library_search ? 'search' : 'lookup')

  return (
    <FormModal
      show
      size="lg"
      title={citation ? 'Edit citation' : `Add citation to “${sectionTitle}”`}
      submitLabel={citation ? 'Save citation' : 'Add citation'}
      // Search and lookup results have their own Add buttons
      hideSubmit={Boolean(adding) && activeTab !== 'manual'}
      isPending={isPending}
      error={error}
      onSubmit={submit}
      onCancel={onCancel}
    >
      {adding ? (
        <Tabs activeKey={activeTab} onSelect={(key) => setTab((key as AddTab) ?? 'lookup')} className="mb-3" mountOnEnter>
          {capabilities.data?.library_search && (
            <Tab eventKey="search" title="Search the library">
              <LibrarySearch onAdd={addFromSource} isAdding={isAddingFromSource} addError={addFromSourceError} />
            </Tab>
          )}
          <Tab eventKey="lookup" title="Look up an identifier">
            <CitationLookup onAdd={addFromSource} isAdding={isAddingFromSource} addError={addFromSourceError} />
          </Tab>
          <Tab eventKey="manual" title="Enter details">
            {bibliographicFields}
          </Tab>
        </Tabs>
      ) : (
        <>
          {bound && (
            <Alert variant="info" className="small d-flex align-items-start gap-2">
              <Books aria-hidden="true" size={20} className="flex-shrink-0" />
              <div>
                These details come from your library's catalogue and update automatically. You can still change
                whether it's required and the notes.
                {onUnlink && (
                  <>
                    {' '}
                    To edit the details yourself,{' '}
                    <Button variant="link" size="sm" className="p-0 align-baseline" onClick={unlink} disabled={unlinking}>
                      {unlinking ? 'unlinking…' : 'unlink it from the catalogue'}
                    </Button>{' '}
                    (it will then stop updating).
                  </>
                )}
                {unlinkError && <div className="text-danger mt-1">{unlinkError}</div>}
              </div>
            </Alert>
          )}
          {bibliographicFields}
        </>
      )}

      <div className={adding ? 'mt-4' : undefined}>{instructorSection}</div>
    </FormModal>
  )
}

export default CitationFormModal
