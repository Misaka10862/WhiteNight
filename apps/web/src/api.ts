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
  sequence: number
  role: 'system' | 'user' | 'assistant'
  kind: 'text' | 'image' | 'tool_result'
  content: string
  image_data_url: string | null
  created_at: string
}

export interface DelegateEvent {
  task_id: string
  executor: 'whitenight' | 'hermes' | 'codex'
  type: 'queued' | 'started' | 'progress' | 'approval_required' | 'artifact' | 'result' | 'error' | 'aborted'
  step: string
  label: string
  detail: string
  progress: number | null
  payload: Record<string, unknown>
  ts: string
}

export type ChatEvent =
  | { type: 'start'; session_id?: string | null }
  | { type: 'chunk'; delta?: string | null }
  | {
      type: 'done'
      session_id?: string | null
      message_id?: string | null
      text?: string | null
      extra?: { task_id?: string | null; user_message_id?: string | null }
    }
  | { type: 'error'; message?: string | null }
  | { type: 'task'; extra?: { delegate_event?: DelegateEvent } }

export interface FactRecord {
  id: string
  key: string
  value: string
  confidence: number
  source_message_ids: string[]
  status: 'active' | 'superseded' | 'deleted'
  conflict_state: 'none' | 'conflicted' | 'resolved'
  created_at: string
  updated_at: string
}

export interface EpisodeRecord {
  id: string
  content: string
  confidence: number
  importance: number
  source_message_ids: string[]
  access_count: number
  created_at: string
  updated_at: string
}

export interface MemoryHit {
  item_type: 'fact' | 'episode'
  item_id: string
  content: string
  score: number
  lexical_score: number
  semantic_score: number | null
}

export interface TaskRecord {
  id: string
  session_id: string | null
  executor: string
  category: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'aborted'
  risk: string
  prompt: string
  cwd: string | null
  thread_id: string | null
  artifacts: Record<string, unknown>[]
  error: string | null
  attempts: number
  created_at: string
  updated_at: string
}

export interface PendingApproval {
  id: string
  code: string
  tool_name: string
  risk: string
  scope: string
  params_summary: string
  session_id: string | null
  channel: string | null
  created_at: string
  expires_at: string | null
}

export interface SessionGrantRecord {
  id: string
  session_id: string
  tool_name: string
  created_at: string
  expires_at: string | null
}

export interface SystemHealth {
  database: { backend: string; reachable: boolean }
  model: Record<string, unknown>
  delegates: Record<string, Record<string, unknown>>
  onebot?: { enabled: boolean; owner_ids: number[]; api_url: string }
}

export interface ProactiveConfig {
  enabled: boolean
  expected_per_day: number
  quiet_start: string
  quiet_end: string
  suppress_minutes: number
  skip_grace_minutes: number
}

export interface ProactiveStatus {
  config: ProactiveConfig
  paused: boolean
  paused_until: string | null
  last_activity_at: string | null
  last_sent_at: string | null
  next_candidate_at: string | null
}

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new Error(`${init?.method ?? 'GET'} ${url} failed: ${response.status} ${body}`)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

// --- sessions / chat ---
export const fetchStatus = () => jsonFetch<StatusResponse>('/api/v1/status')
export const fetchSessions = () => jsonFetch<SessionSummary[]>('/api/v1/sessions')
export const createSession = (title?: string) =>
  jsonFetch<SessionSummary>('/api/v1/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
export const renameSession = (id: string, title: string) =>
  jsonFetch<SessionSummary>(`/api/v1/sessions/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
export const deleteSession = (id: string) =>
  jsonFetch<void>(`/api/v1/sessions/${id}`, { method: 'DELETE' })
export const fetchMessages = (sessionId: string) =>
  jsonFetch<MessageRecord[]>(`/api/v1/sessions/${sessionId}/messages`)
export async function exportSession(id: string, format: 'markdown' | 'jsonl'): Promise<void> {
  const response = await fetch(`/api/v1/sessions/${id}/export?fmt=${format}`)
  if (!response.ok) throw new Error(`export failed: ${response.status}`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `session-${id}.${format === 'jsonl' ? 'jsonl' : 'md'}`
  anchor.click()
  URL.revokeObjectURL(url)
}

// --- memory ---
export const fetchFacts = () => jsonFetch<FactRecord[]>('/api/v1/memory/facts')
export const createFact = (payload: { key: string; value: string; confidence?: number }) =>
  jsonFetch<FactRecord>('/api/v1/memory/facts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
export const updateFact = (id: string, value: string) =>
  jsonFetch<FactRecord>(`/api/v1/memory/facts/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })
export const deleteFact = (id: string) =>
  jsonFetch<void>(`/api/v1/memory/facts/${id}`, { method: 'DELETE' })
export const resolveFact = (id: string, keep: boolean) =>
  jsonFetch<FactRecord | null>(`/api/v1/memory/facts/${id}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keep }),
  })
export const fetchEpisodes = () => jsonFetch<EpisodeRecord[]>('/api/v1/memory/episodes')
export const createEpisode = (payload: { content: string; importance?: number; confidence?: number }) =>
  jsonFetch<EpisodeRecord>('/api/v1/memory/episodes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
export const deleteEpisode = (id: string) =>
  jsonFetch<void>(`/api/v1/memory/episodes/${id}`, { method: 'DELETE' })
export const retrieveMemory = (query: string) =>
  jsonFetch<MemoryHit[]>(`/api/v1/memory/retrieve?query=${encodeURIComponent(query)}&limit=10`)
export async function exportMemory(format: 'markdown' | 'jsonl'): Promise<void> {
  const response = await fetch(`/api/v1/memory/export?fmt=${format}`)
  if (!response.ok) throw new Error(`memory export failed: ${response.status}`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `whitenight-memory.${format === 'jsonl' ? 'jsonl' : 'md'}`
  anchor.click()
  URL.revokeObjectURL(url)
}

// --- tasks / approvals / policy / system ---
export const fetchTasks = (sessionId?: string) =>
  jsonFetch<TaskRecord[]>(sessionId ? `/api/v1/tasks?session_id=${sessionId}` : '/api/v1/tasks')
export const abortTask = (id: string) =>
  jsonFetch<TaskRecord>(`/api/v1/tasks/${id}/abort`, { method: 'POST' })
export const fetchPendingApprovals = () =>
  jsonFetch<PendingApproval[]>('/api/v1/approvals/pending')
export const approveRequest = (code: string, sessionId?: string | null) =>
  jsonFetch<{ ok: boolean; reason: string; scope: string }>(`/api/v1/approvals/${code}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId ?? null }),
  })
export const rejectRequest = (code: string) =>
  jsonFetch<{ ok: boolean; reason: string }>(`/api/v1/approvals/${code}/reject`, { method: 'POST' })
export const fetchPolicyRules = () =>
  jsonFetch<{ tool: string; risk: string }[]>('/api/v1/policy/rules')
export const fetchSessionGrants = () =>
  jsonFetch<SessionGrantRecord[]>('/api/v1/policy/grants')
export const revokeGrant = (id: string) =>
  jsonFetch<void>(`/api/v1/policy/grants/${id}`, { method: 'DELETE' })
export const fetchSystemHealth = () => jsonFetch<SystemHealth>('/api/v1/system/health')
export const fetchProactiveStatus = () => jsonFetch<ProactiveStatus>('/api/v1/proactive/status')
export const updateProactiveConfig = (config: ProactiveConfig) =>
  jsonFetch<ProactiveStatus>('/api/v1/proactive/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
export const pauseProactive = (until?: string | null) =>
  jsonFetch<ProactiveStatus>('/api/v1/proactive/pause', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ until: until ?? null }),
  })
export const resumeProactive = () =>
  jsonFetch<ProactiveStatus>('/api/v1/proactive/resume', { method: 'POST' })
export const fetchRuleFile = async (name: 'SOUL' | 'AGENTS'): Promise<string> => {
  const response = await fetch(`/api/v1/rules/${name}`)
  if (!response.ok) throw new Error(`rule ${name} failed: ${response.status}`)
  return response.text()
}
export const saveRuleFile = async (name: 'SOUL' | 'AGENTS', content: string): Promise<void> => {
  const response = await fetch(`/api/v1/rules/${name}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  if (!response.ok) throw new Error(`save ${name} failed: ${response.status}`)
}

export function chatWebSocketUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}/api/v1/chat/ws`
}
