import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Container, Spinner } from 'react-bootstrap'
import { LinkBreak } from '@phosphor-icons/react'
import { useQueryClient } from '@tanstack/react-query'
import apiClient from '@/api/client'
import { useAuthStore, type AuthTokens } from '@/stores/auth'
import { apiErrorMessage } from '@/lib/apiError'
import { EmptyState } from '@/components/common/EmptyState'

interface ExchangeResponse extends AuthTokens {
  next: string
}

/** Only follow same-origin paths, never "//other.site" or absolute URLs */
const isLocalPath = (path: string) => path.startsWith('/') && !path.startsWith('//')

/**
 * Landing page after an LTI launch (/launch?code=…): swaps the one-time code for
 * tokens, then opens the reading list. The code expires after 60 seconds and works once.
 */
export default function LaunchView() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const setTokens = useAuthStore((s) => s.setTokens)
  const [error, setError] = useState<string | null>(null)
  const started = useRef(false)

  useEffect(() => {
    // StrictMode runs effects twice in development; the code only works once
    if (started.current) return
    started.current = true

    const code = params.get('code')
    if (!code) {
      setError('This sign-in link is incomplete. Open Stacks again from your course.')
      return
    }
    apiClient
      .post<ExchangeResponse>('/auth/lti/exchange', { code })
      .then(({ data }) => {
        queryClient.clear() // drop anything cached for a previous user
        setTokens(data)
        navigate(isLocalPath(data.next) ? data.next : '/lists', { replace: true })
      })
      .catch((err) =>
        setError(apiErrorMessage(err, 'Stacks could not sign you in. Open Stacks again from your course.'))
      )
  }, [params, navigate, queryClient, setTokens])

  if (error) {
    return (
      <Container className="py-5">
        <EmptyState icon={LinkBreak} heading="Stacks couldn't open">
          {error}
        </EmptyState>
      </Container>
    )
  }

  return (
    <Container className="py-5 text-center">
      <Spinner animation="border" role="status">
        <span className="visually-hidden">Opening your reading list…</span>
      </Spinner>
    </Container>
  )
}
