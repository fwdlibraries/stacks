import { useState } from 'react'
import { Form } from 'react-bootstrap'
import { FieldLabel, FormModal } from '@/components/common/FormModal'
import type { ListDetailsInput, ReadingListSummary, Visibility } from '@/api/hooks/useLists'

const VISIBILITY_OPTIONS: { value: Visibility; label: string; help: string }[] = [
  { value: 'public', label: 'Public', help: 'Anyone with the course link can see the published list.' },
  { value: 'unlisted', label: 'Unlisted', help: 'Same as public for now; intended to be hidden from search.' },
  {
    value: 'institution',
    label: 'Organization only',
    help: 'Only signed-in members of your organization. Students cannot see it yet.',
  },
]

interface ListDetailsModalProps {
  list: ReadingListSummary
  isPending: boolean
  error?: string | null
  onSubmit: (input: ListDetailsInput) => void
  onCancel: () => void
  /** False when the user may edit but not publish: visibility is a publishing decision */
  canChangeVisibility?: boolean
}

export function ListDetailsModal({
  list,
  isPending,
  error,
  onSubmit,
  onCancel,
  canChangeVisibility = true,
}: ListDetailsModalProps) {
  const [title, setTitle] = useState(list.title)
  const [description, setDescription] = useState(list.description ?? '')
  const [visibility, setVisibility] = useState<Visibility>(list.visibility)
  const [touched, setTouched] = useState(false)
  const titleMissing = !title.trim()

  const submit = () => {
    setTouched(true)
    if (titleMissing) return
    onSubmit(canChangeVisibility ? { title, description, visibility } : { title, description })
  }

  return (
    <FormModal
      show
      title="Reading list details"
      submitLabel="Save details"
      isPending={isPending}
      error={error}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <Form.Group className="mb-3" controlId="list-title">
        <FieldLabel required>Title</FieldLabel>
        <Form.Control
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          isInvalid={touched && titleMissing}
          autoFocus
        />
        <Form.Control.Feedback type="invalid">Enter a title for the reading list.</Form.Control.Feedback>
      </Form.Group>
      <Form.Group className="mb-3" controlId="list-description">
        <FieldLabel>Description</FieldLabel>
        <Form.Control
          as="textarea"
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Form.Group>
      <fieldset className="mb-3" disabled={!canChangeVisibility}>
        <legend className="form-label fs-6">Visibility</legend>
        {!canChangeVisibility && (
          <p className="small text-body-secondary">You can't change who sees this list.</p>
        )}
        {VISIBILITY_OPTIONS.map((option) => (
          <Form.Check
            key={option.value}
            type="radio"
            id={`visibility-${option.value}`}
            name="visibility"
            className="mb-2"
            checked={visibility === option.value}
            onChange={() => setVisibility(option.value)}
            label={
              <>
                {option.label}
                <span className="d-block small text-body-secondary">{option.help}</span>
              </>
            }
          />
        ))}
      </fieldset>
    </FormModal>
  )
}

export default ListDetailsModal
