import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Spinner } from 'react-bootstrap'
import { useAuthStore } from '@/stores/auth'

/** Redirects to /login when there is no session (after trying to restore one),
 * remembering where the user was headed. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const token = useAuthStore((s) => s.token)
  const status = useAuthStore((s) => s.status)
  const location = useLocation()

  if (!token && status === 'restoring') {
    return (
      <Spinner animation="border" role="status" className="m-4">
        <span className="visually-hidden">Loading…</span>
      </Spinner>
    )
  }
  if (!token) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return <>{children}</>
}

export default RequireAuth
