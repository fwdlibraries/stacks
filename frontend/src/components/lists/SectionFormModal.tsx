import { useState } from 'react'
import { Form } from 'react-bootstrap'
import { FieldLabel, FormModal } from '@/components/common/FormModal'
import type { ListSection, SectionInput } from '@/api/hooks/useLists'

interface SectionFormModalProps {
  /** Existing section to edit; omit to add a new one */
  section?: ListSection
  isPending: boolean
  error?: string | null
  onSubmit: (input: SectionInput) => void
  onCancel: () => void
}

/** Mount with a `key` per section so the fields reset when it changes. */
export function SectionFormModal({ section, isPending, error, onSubmit, onCancel }: SectionFormModalProps) {
  const [title, setTitle] = useState(section?.title ?? '')
  const [description, setDescription] = useState(section?.description ?? '')
  const [touched, setTouched] = useState(false)
  const titleMissing = !title.trim()

  const submit = () => {
    setTouched(true)
    if (titleMissing) return
    onSubmit({ title, description })
  }

  return (
    <FormModal
      show
      title={section ? 'Edit section' : 'Add section'}
      submitLabel={section ? 'Save section' : 'Add section'}
      isPending={isPending}
      error={error}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <Form.Group className="mb-3" controlId="section-title">
        <FieldLabel required>Title</FieldLabel>
        <Form.Control
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          isInvalid={touched && titleMissing}
          placeholder="Required, Week 1, Supplemental…"
          autoFocus
        />
        <Form.Control.Feedback type="invalid">Enter a section title.</Form.Control.Feedback>
      </Form.Group>
      <Form.Group className="mb-3" controlId="section-description">
        <FieldLabel>Description</FieldLabel>
        <Form.Control
          as="textarea"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <Form.Text>Shown to students under the section title.</Form.Text>
      </Form.Group>
    </FormModal>
  )
}

export default SectionFormModal
