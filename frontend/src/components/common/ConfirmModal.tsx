import type { ReactNode } from 'react'
import { Alert, Button, Modal } from 'react-bootstrap'

interface ConfirmModalProps {
  show: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  confirmVariant?: 'primary' | 'danger'
  isPending?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmModal({
  show,
  title,
  children,
  confirmLabel,
  confirmVariant = 'danger',
  isPending = false,
  error,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  return (
    <Modal show={show} onHide={onCancel} centered>
      <Modal.Header closeButton>
        <Modal.Title as="h2" className="h3">
          {title}
        </Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {children}
        {error && (
          <Alert variant="danger" className="small mt-3 mb-0">
            {error}
          </Alert>
        )}
      </Modal.Body>
      <Modal.Footer>
        <Button variant="outline-secondary" onClick={onCancel} disabled={isPending}>
          Cancel
        </Button>
        <Button variant={confirmVariant} onClick={onConfirm} disabled={isPending}>
          {confirmLabel}
        </Button>
      </Modal.Footer>
    </Modal>
  )
}

export default ConfirmModal
