import type { ReactNode } from 'react'
import type { Icon } from '@phosphor-icons/react'

interface EmptyStateProps {
  icon: Icon
  heading: string
  children: ReactNode
  action?: ReactNode
}

/**
 * Empty state pattern from the style guide: Duotone Phosphor icon in secondary grey,
 * a short heading, one sentence of body text, and an optional action.
 */
export function EmptyState({ icon: IconComponent, heading, children, action }: EmptyStateProps) {
  return (
    <div className="text-center py-5 px-3">
      <IconComponent
        size={48}
        weight="duotone"
        color="var(--stacks-muted)"
        aria-hidden="true"
        className="mb-3"
      />
      <h2 className="h3 mb-2">{heading}</h2>
      <p className="text-body-secondary mb-3 mx-auto" style={{ maxWidth: '32rem' }}>
        {children}
      </p>
      {action}
    </div>
  )
}

export default EmptyState
