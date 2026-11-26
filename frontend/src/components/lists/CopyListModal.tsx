import { useState } from 'react'
import { Form } from 'react-bootstrap'
import { Link } from 'react-router-dom'
import { isAxiosError } from 'axios'
import { FieldLabel, FormModal } from '@/components/common/FormModal'
import { useCopyList, useTerms, type ReadingListSummary } from '@/api/hooks/useLists'
import { apiErrorMessage } from '@/lib/apiError'

interface CopyListModalProps {
  list: ReadingListSummary
  onCopied: (copy: ReadingListSummary) => void
  onCancel: () => void
}

/** Copy a list into another term as a draft: the start of that term's own list. */
export function CopyListModal({ list, onCopied, onCancel }: CopyListModalProps) {
  const terms = useTerms()
  const copy = useCopyList(list.id)
  const choices = (terms.data ?? []).filter((t) => !(list.kind === 'section' && list.term?.code === t.code))
  const [termId, setTermId] = useState('')
  const [section, setSection] = useState('')
  const [touched, setTouched] = useState(false)

  // 409: that term already has its own list; offer to open it
  const existing =
    isAxiosError(copy.error) && copy.error.response?.status === 409
      ? (copy.error.response.data as { detail?: { list_id?: string } }).detail?.list_id
      : undefined

  const submit = () => {
    setTouched(true)
    if (!termId) return
    copy.mutate({ term_id: termId, section: section.trim() || null }, { onSuccess: onCopied })
  }

  return (
    <FormModal
      show
      title="Copy to another term"
      submitLabel="Copy list"
      isPending={copy.isPending}
      error={copy.error ? apiErrorMessage(copy.error, 'The list could not be copied. Try again.') : null}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <p className="text-body-secondary">
        Makes a draft copy of this list (sections, citations and notes) for the same course in another term.
        Students in that term see the copy once it's published; this list doesn't change.
      </p>
      <Form.Group className="mb-3" controlId="copy-term">
        <FieldLabel required>Term</FieldLabel>
        <Form.Select
          value={termId}
          onChange={(e) => setTermId(e.target.value)}
          isInvalid={touched && !termId}
          disabled={terms.isLoading}
        >
          <option value="">{terms.isLoading ? 'Loading terms…' : 'Choose a term'}</option>
          {choices.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
              {t.name !== t.code ? ` (${t.code})` : ''}
            </option>
          ))}
        </Form.Select>
        <Form.Control.Feedback type="invalid">Choose the term to copy into.</Form.Control.Feedback>
        {terms.data && choices.length === 0 && (
          <Form.Text>No other terms yet. An administrator can add them under Administration › Terms.</Form.Text>
        )}
      </Form.Group>
      <Form.Group className="mb-3" controlId="copy-section">
        <FieldLabel>Section</FieldLabel>
        <Form.Control value={section} onChange={(e) => setSection(e.target.value)} placeholder="e.g. a CRN" />
        <Form.Text>Leave blank for the course as a whole in that term.</Form.Text>
      </Form.Group>
      {existing && (
        <p className="small mb-2">
          <Link to={`/lists/${existing}`} onClick={onCancel}>
            Open that term’s list
          </Link>
        </p>
      )}
    </FormModal>
  )
}
