import { useAuthStore } from '@/stores/auth'
/**
 * WebSocket client for real-time collaboration.
 *
 * Manages a single persistent connection per authenticated session.
 * Subscribes to a list "room" on navigation.
 * Automatically reconnects with exponential backoff.
 */

export type WSMessageType =
  | 'presence.join'
  | 'presence.leave'
  | 'citation.created'
  | 'citation.updated'
  | 'citation.deleted'
  | 'citation.locked'
  | 'citation.unlocked'
  | 'import.progress'
  | 'import.ready_for_review'
  | 'section.reordered'

export interface WSMessage {
  type: WSMessageType
  [key: string]: unknown
}

type MessageHandler = (message: WSMessage) => void

class StacksWebSocket {
  private ws: WebSocket | null = null
  private listId: string | null = null
  private handlers: Set<MessageHandler> = new Set()
  private reconnectDelay = 1000
  private maxReconnectDelay = 30000
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private intentionallyClosed = false

  connect(listId: string) {
    this.listId = listId
    this.intentionallyClosed = false
    this._connect()
  }

  disconnect() {
    this.intentionallyClosed = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
    }
    this.ws?.close()
    this.ws = null
    this.listId = null
  }

  subscribe(handler: MessageHandler) {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  send(message: WSMessage) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
    }
  }

  private _connect() {
    if (!this.listId) return

    const token = useAuthStore.getState().token
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/api/v1/ws/lists/${this.listId}?token=${token}`

    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      console.debug('[Stacks WS] Connected to list', this.listId)
      this.reconnectDelay = 1000 // reset backoff on successful connect
    }

    this.ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data)
        this.handlers.forEach((handler) => handler(message))
      } catch (e) {
        console.error('[Stacks WS] Failed to parse message', e)
      }
    }

    this.ws.onclose = () => {
      if (!this.intentionallyClosed) {
        console.debug('[Stacks WS] Connection closed, reconnecting in', this.reconnectDelay, 'ms')
        this.reconnectTimer = setTimeout(() => {
          this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay)
          this._connect()
        }, this.reconnectDelay)
      }
    }

    this.ws.onerror = (error) => {
      console.error('[Stacks WS] Error', error)
    }
  }
}

// Singleton — one connection per browser tab
export const stacksWS = new StacksWebSocket()
