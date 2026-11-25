import { useSearchParams } from 'react-router-dom'
import { Alert, Button, Card, ListGroup } from 'react-bootstrap'
import { PuzzlePiece } from '@phosphor-icons/react'
import { useConnectExtension, useDisconnectExtension, useExtensionConnections } from '@/api/hooks/useExtension'
import { apiErrorMessage } from '@/lib/apiError'
import { isExtensionReturn } from '@/lib/extension'

const formatDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : 'never'

/** Where the Stacks browser extension sends people to connect it */
export default function ConnectExtensionView() {
  const [params] = useSearchParams()
  const returnTo = params.get('return')
  const browser = (params.get('browser') ?? 'Browser').slice(0, 40)
  const connections = useExtensionConnections()
  const connect = useConnectExtension()
  const disconnect = useDisconnectExtension()
  const valid = isExtensionReturn(returnTo)

  const doConnect = () => {
    if (!valid) return
    connect.mutate(browser, {
      onSuccess: ({ token }) => {
        // The token travels in the fragment, which never reaches a server
        const fragment = new URLSearchParams({ token, base: window.location.origin })
        window.location.assign(`${returnTo}#${fragment.toString()}`)
      },
    })
  }

  return (
    <div style={{ maxWidth: '640px' }}>
      <h1 className="d-flex align-items-center gap-2">
        <PuzzlePiece aria-hidden="true" /> Browser extension
      </h1>

      {returnTo && !valid && (
        <Alert variant="danger">This connection request didn't come from the Stacks extension, so it was ignored.</Alert>
      )}

      {valid && (
        <Card className="mb-4">
          <Card.Body>
            <Card.Title as="h2" className="h4">
              Connect the Stacks extension ({browser})?
            </Card.Title>
            <p>
              The extension will be able to see your organization's reading lists and add citations to them. It
              can't change or delete anything else, and you can disconnect it here at any time.
            </p>
            {connect.isError && (
              <Alert variant="danger" className="small">
                {apiErrorMessage(connect.error, 'The extension could not be connected.')}
              </Alert>
            )}
            <Button onClick={doConnect} disabled={connect.isPending}>
              {connect.isPending ? 'Connecting…' : 'Connect'}
            </Button>
          </Card.Body>
        </Card>
      )}

      <h2 className="h4">Connected extensions</h2>
      {connections.data?.length === 0 && <p className="text-body-secondary">None.</p>}
      {connections.data && connections.data.length > 0 && (
        <ListGroup>
          {connections.data.map((c) => (
            <ListGroup.Item key={c.id} className="d-flex justify-content-between align-items-center gap-3">
              <div>
                <div>{c.name}</div>
                <div className="small text-body-secondary">
                  Connected {formatDate(c.created_at)} · last used {formatDate(c.last_used_at)}
                </div>
              </div>
              <Button
                variant="outline-danger"
                size="sm"
                onClick={() => disconnect.mutate(c.id)}
                disabled={disconnect.isPending}
              >
                Disconnect
              </Button>
            </ListGroup.Item>
          ))}
        </ListGroup>
      )}
    </div>
  )
}
