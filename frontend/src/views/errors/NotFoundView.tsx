import type { ReactNode } from 'react'
import { Container } from 'react-bootstrap'
import { MagnifyingGlass } from '@phosphor-icons/react'
import { EmptyState } from '@/components/common/EmptyState'

interface NotFoundViewProps {
  /** Optional action, e.g. a link back to reading lists in the editor */
  action?: ReactNode
}

export default function NotFoundView({ action }: NotFoundViewProps) {
  return (
    <Container className="py-5">
      <EmptyState icon={MagnifyingGlass} heading="Page not found" action={action}>
        The address may be mistyped, or the page may have moved. If you followed a link from your
        course, contact your instructor or librarian.
      </EmptyState>
    </Container>
  )
}
