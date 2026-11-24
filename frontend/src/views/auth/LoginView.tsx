import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate, type Location } from 'react-router-dom'
import { Alert, Button, Card, Container, Form } from 'react-bootstrap'
import { isAxiosError } from 'axios'
import { useLogin } from '@/api/hooks/useAuth'
import { useAuthStore } from '@/stores/auth'

export default function LoginView() {
  const navigate = useNavigate()
  const location = useLocation()
  const token = useAuthStore((s) => s.token)
  const login = useLogin()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const from = (location.state as { from?: Location } | null)?.from?.pathname ?? '/lists'

  if (token) {
    return <Navigate to={from} replace />
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    login.mutate({ email, password }, { onSuccess: () => navigate(from, { replace: true }) })
  }

  const errorMessage = login.isError
    ? isAxiosError(login.error) && login.error.response?.status === 401
      ? 'Incorrect email or password.'
      : 'Sign-in is unavailable right now. Try again in a few minutes.'
    : null

  return (
    <Container className="py-5" style={{ maxWidth: '28rem' }}>
      <div className="text-center mb-4">
        <img src="/favicon.svg" alt="" width={56} height={56} className="mb-2" />
        <h1 className="stacks-wordmark mb-1" style={{ fontSize: '2rem' }}>
          Stacks
        </h1>
        <p className="text-caps text-body-secondary mb-0">Course reading lists</p>
      </div>

      <Card>
        <Card.Body className="p-4">
          <h2 className="h3 mb-3">Sign in</h2>
          <p className="small text-body-secondary">
            Instructors usually sign in from the LMS. Use this form for a local Stacks account.
          </p>

          {errorMessage && (
            <Alert variant="danger" className="small">
              {errorMessage}
            </Alert>
          )}

          <Form onSubmit={handleSubmit} noValidate>
            <Form.Group className="mb-3" controlId="login-email">
              <Form.Label>
                Email<span className="required-mark" aria-hidden="true">*</span>
              </Form.Label>
              <Form.Control
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Form.Group>
            <Form.Group className="mb-4" controlId="login-password">
              <Form.Label>
                Password<span className="required-mark" aria-hidden="true">*</span>
              </Form.Label>
              <Form.Control
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Form.Group>
            <div className="d-grid d-md-block">
              <Button type="submit" variant="primary" disabled={login.isPending || !email || !password}>
                {login.isPending ? 'Signing in…' : 'Sign in'}
              </Button>
            </div>
          </Form>
        </Card.Body>
      </Card>
    </Container>
  )
}
