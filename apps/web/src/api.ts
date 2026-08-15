export interface StatusResponse {
  name: string
  version: string
  env: string
  host: string
  port: number
  database: {
    url_backend: 'sqlite' | 'sqlcipher'
    reachable: boolean
  }
  model: Record<string, unknown>
}

export interface SessionSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface MessageRecord {
  id: string
  session_id: string
  role: 'system' | 'user' | 'assistant'
  kind: 'text' | 'image' | 'tool_result'
  content: string
  image_data_url: string | null
  created_at: string
}

export type ChatEvent =
  | { type: 'start'; session_id?: string | null }
  | { type: 'chunk'; delta?: string | null }
  | { type: 'done'; session_id?: string | null; message_id?: string | null; text?: string | null }
  | { type: 'error'; message?: string | null }

export async function fetchStatus(): Promise<StatusResponse> {
  const response = await fetch('/api/v1/status')
  if (!response.ok) {
    throw new Error(`status request failed: ${response.status}`)
  }
  return (await response.json()) as StatusResponse
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const response = await fetch('/api/v1/sessions')
  if (!response.ok) throw new Error(`sessions failed: ${response.status}`)
  return (await response.json()) as SessionSummary[]
}

export async function createSession(title?: string): Promise<SessionSummary> {
  const response = await fetch('/api/v1/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!response.ok) throw new Error(`create session failed: ${response.status}`)
  return (await response.json()) as SessionSummary
}

export async function fetchMessages(sessionId: string): Promise<MessageRecord[]> {
  const response = await fetch(`/api/v1/sessions/${sessionId}/messages`)
  if (!response.ok) throw new Error(`messages failed: ${response.status}`)
  return (await response.json()) as MessageRecord[]
}

export function chatWebSocketUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}/api/v1/chat/ws`
}
