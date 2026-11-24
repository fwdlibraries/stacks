import type { FormEvent, ReactNode } from 'react'
import { Alert, Button, Form, Modal } from 'react-bootstrap'

interface FormModalProps {
  show: boolean
  title: string
  submitLabel: string
  isPending?: boolean
  error?: string | null
  size?: 'lg'
  /** Hide the submit button, e.g. while another action in the body adds the item */
  hideSubmit?: boolean
  onSubmit: () => void
  onCancel: () => void
  children: ReactNode
}

/** Modal wrapping a form: Enter submits, errors from the server show above the buttons. */
export function FormModal({
  show,
  title,
  submitLabel,
  isPending = false,
  error,
  size,
  hideSubmit = false,
  onSubmit,
  onCancel,
  children,
}: FormModalProps) {
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit()
  }

  return (
    <Modal show={show} onHide={onCancel} centered size={size} backdrop="static">
      <Form onSubmit={handleSubmit} noValidate>
        <Modal.Header closeButton>
          <Modal.Title as="h2" className="h3">
            {title}
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {children}
          {error && (
            <Alert variant="danger" className="small mb-0">
              {error}
            </Alert>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="outline-secondary" onClick={onCancel} disabled={isPending}>
            Cancel
          </Button>
          {!hideSubmit && (
            <Button type="submit" variant="primary" disabled={isPending}>
              {isPending ? 'Saving…' : submitLabel}
            </Button>
          )}
        </Modal.Footer>
      </Form>
    </Modal>
  )
}

/** Label with the style guide's Warm Grey required asterisk */
export function FieldLabel({ children, required = false }: { children: ReactNode; required?: boolean }) {
  return (
    <Form.Label>
      {children}
      {required && (
        <span className="required-mark" aria-hidden="true">
          *
        </span>
      )}
    </Form.Label>
  )
}

export default FormModal
