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
  character_id: string | null
  persona_id: string | null
  character_name: string | null
  character_avatar_path: string | null
}

export interface CharacterCardData {
  name: string
  description: string
  personality: string
  scenario: string
  first_mes: string
  mes_example: string
  creator_notes: string
  system_prompt: string
  post_history_instructions: string
  alternate_greetings: string[]
  tags: string[]
  creator: string
  character_version: string
  extensions: Record<string, unknown>
  character_book?: Record<string, unknown> | null
  [key: string]: unknown
}

export interface CharacterCard {
  spec: 'chara_card_v2' | 'chara_card_v3'
  spec_version: string
  data: CharacterCardData
  [key: string]: unknown
}

export interface CharacterRecord {
  id: string
  name: string
  revision_id: string
  revision: number
  card: CharacterCard
  content_hash: string
  avatar_path: string | null
  is_default: boolean
  archived_at: string | null
}

export interface PersonaRecord {
  id: string
  name: string
  description: string
  content_hash: string
}

export interface PromptBlock {
  id: string
  name: string
  role: 'system' | 'user' | 'assistant'
  content: string
  enabled: boolean
  position: 'relative' | 'in_chat'
  depth: number
  order: number
  triggers: string[]
  outlet: string | null
}

export interface PromptProfile {
  id: string
  character_id: string
  revision: number
  blocks: PromptBlock[]
  content_hash: string
}

export interface LorebookEntry {
  id: string
  comment: string
  content: string
  keys: string[]
  secondary_keys: string[]
  secondary_logic: 'and_any' | 'and_all' | 'not_any' | 'not_all'
  enabled: boolean
  constant: boolean
  position: string
  depth: number
  role: 'system' | 'user' | 'assistant'
  order: number
  probability: number
  group: string
  group_override: boolean
  group_weight: number
  sticky: number
  cooldown: number
  delay: number
  scan_depth: number | null
  case_sensitive: boolean
  match_whole_words: boolean
  prevent_recursion: boolean
  exclude_recursion: boolean
  delay_until_recursion: number
  triggers: string[]
  ignore_budget: boolean
  outlet: string
  match_persona: boolean
  match_character: boolean
  match_scenario: boolean
  extensions: Record<string, unknown>
}

export interface LorebookData {
  name: string
  entries: LorebookEntry[]
  scan_depth: number
  token_budget: number
  recursive: boolean
  max_recursion_steps: number
  min_activations: number
  extensions: Record<string, unknown>
}

export interface LorebookRecord {
  id: string
  revision: number
  data: LorebookData
  content_hash: string
  globally_enabled: boolean
  archived_at: string | null
}

export interface PromptPreview {
  messages: Array<Record<string, unknown>>
  manifest: Array<{
    id: string
    name: string
    role: string
    source: string
    enabled: boolean
    depth: number
    token_count: number | null
    content_hash: string
  }>
  activated_lore: Array<Record<string, unknown>>
  seed: string
  tokenizer: 'exact' | 'unavailable'
  total_tokens: number | null
  character_revision_id: string
  prompt_profile_revision: number
}

export interface MessageRecord {
  id: string
  session_id: string
  sequence: number
  role: 'system' | 'user' | 'assistant' | 'tool'
  kind: 'text' | 'image' | 'tool_call' | 'tool_result'
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
      extra?: { task_id?: string | null; user_message_id?: string | null; sticker_ids?: string[] }
    }
  | { type: 'error'; message?: string | null }
  | { type: 'task'; extra?: { delegate_event?: DelegateEvent } }
  | {
      type: 'tool'
      extra?: { tool_name?: string; status?: string; message?: string }
    }
  | {
      type: 'approval'
      text?: string | null
      extra?: { approval_id?: string; approval_code?: string; tool_name?: string }
    }

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
  character_id: string | null
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
  character_id: string | null
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
  onebot?: {
    enabled: boolean
    owner_ids: number[]
    api_url: string
    health?: { reachable: boolean; logged_in: boolean; reason: string; http_status?: number; last_error?: string | null }
    stickers?: { configured: boolean; native_ready: number }
  }
}

export interface ModelConfig {
  provider: 'ollama' | 'openai'
  providers: Array<'ollama' | 'openai'>
  model_name: string
  base_url: string
  api_key_account: string
  api_key_configured: boolean
  ollama_keep_alive: string
  options: string[]
  tokenizer_path: string
  tokenizer_available: boolean
  context_tokens: number
}

export interface ModelProviderUpdate {
  provider: 'ollama' | 'openai'
  model_name: string
  base_url: string
  api_key?: string
}

export interface ModelListRequest {
  provider: 'ollama' | 'openai'
  base_url: string
  api_key?: string
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
  delivery?: {
    configured_sender: 'log' | 'none' | 'qq'
    active_sender: 'log' | 'none' | 'qq' | 'unavailable'
    target_user_id: number | null
    onebot_reachable: boolean | null
    available: boolean
    reason: string
  }
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
export const createSession = (payload?: { title?: string; character_id?: string; persona_id?: string; greeting_index?: number }) =>
  jsonFetch<SessionSummary>('/api/v1/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload ?? {}),
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
export const fetchFacts = (characterId?: string | null) =>
  jsonFetch<FactRecord[]>(characterId ? `/api/v1/memory/facts?character_id=${encodeURIComponent(characterId)}` : '/api/v1/memory/facts')
export const createFact = (payload: { key: string; value: string; confidence?: number; character_id?: string | null }) =>
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
export const fetchEpisodes = (characterId?: string | null) =>
  jsonFetch<EpisodeRecord[]>(characterId ? `/api/v1/memory/episodes?character_id=${encodeURIComponent(characterId)}` : '/api/v1/memory/episodes')
export const createEpisode = (payload: { content: string; importance?: number; confidence?: number; character_id?: string | null }) =>
  jsonFetch<EpisodeRecord>('/api/v1/memory/episodes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
export const deleteEpisode = (id: string) =>
  jsonFetch<void>(`/api/v1/memory/episodes/${id}`, { method: 'DELETE' })
export const retrieveMemory = (query: string, characterId?: string | null) =>
  jsonFetch<MemoryHit[]>(`/api/v1/memory/retrieve?query=${encodeURIComponent(query)}&limit=10${characterId ? `&character_id=${encodeURIComponent(characterId)}` : ''}`)
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
  jsonFetch<{
    ok: boolean
    reason: string
    scope: string
    execution_status?: string
    message_id?: string | null
  }>(`/api/v1/approvals/${code}/approve`, {
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
export const fetchModelConfig = () => jsonFetch<ModelConfig>('/api/v1/model/config')
export const updateModelProvider = (config: ModelProviderUpdate) =>
  jsonFetch<{
    provider: 'ollama' | 'openai'
    model_name: string
    base_url: string
    api_key_configured: boolean
    persisted: boolean
  }>('/api/v1/model/provider', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
export const fetchAvailableModels = (request: ModelListRequest) =>
  jsonFetch<{ provider: 'ollama' | 'openai'; models: string[] }>('/api/v1/model/models', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
export const restartService = () =>
  jsonFetch<{ accepted: boolean; service: string }>('/api/v1/service/restart', { method: 'POST' })
export const updateModelKeepAlive = (ollama_keep_alive: string) =>
  jsonFetch<{ ollama_keep_alive: string; persisted: boolean }>('/api/v1/model/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keep_alive: ollama_keep_alive }),
  })
export const updateTokenizerPath = (path: string) =>
  jsonFetch<{ path: string; available: boolean }>('/api/v1/model/tokenizer', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })

// --- characters / persona / lorebooks / prompt compiler ---
export const fetchCharacters = () => jsonFetch<CharacterRecord[]>('/api/v1/characters')
export const importCharacter = (card: CharacterCard, avatarDataUrl?: string | null) =>
  jsonFetch<CharacterRecord>('/api/v1/characters/import', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ card, avatar_data_url: avatarDataUrl ?? null }),
  })
export const updateCharacter = (id: string, card: CharacterCard) =>
  jsonFetch<CharacterRecord>(`/api/v1/characters/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(card),
  })
export const archiveCharacter = (id: string) =>
  jsonFetch<void>(`/api/v1/characters/${id}/archive`, { method: 'POST' })
export const fetchCharacterRevisions = (id: string) =>
  jsonFetch<Array<{ id: string; revision: number; content_hash: string; created_at: string }>>(`/api/v1/characters/${id}/revisions`)
export const restoreCharacterRevision = (id: string, revisionId: string) =>
  jsonFetch<CharacterRecord>(`/api/v1/characters/${id}/revisions/${revisionId}/restore`, { method: 'POST' })
export const exportCharacter = (id: string) =>
  jsonFetch<{ card: CharacterCard; avatar_data_url: string | null }>(`/api/v1/characters/${id}/export`)
export const fetchPersona = () => jsonFetch<PersonaRecord>('/api/v1/persona')
export const updatePersona = (name: string, description: string) =>
  jsonFetch<PersonaRecord>('/api/v1/persona', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, description }),
  })
export const fetchPromptProfile = (characterId: string) =>
  jsonFetch<PromptProfile>(`/api/v1/prompt-profiles/${characterId}`)
export const updatePromptProfile = (characterId: string, blocks: PromptBlock[]) =>
  jsonFetch<PromptProfile>(`/api/v1/prompt-profiles/${characterId}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ blocks }),
  })
export const fetchLorebooks = () => jsonFetch<LorebookRecord[]>('/api/v1/lorebooks')
export const createLorebook = (data: LorebookData, characterId?: string) =>
  jsonFetch<LorebookRecord>('/api/v1/lorebooks', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data, globally_enabled: false, character_id: characterId ?? null }),
  })
export const updateLorebook = (id: string, data: LorebookData) =>
  jsonFetch<LorebookRecord>(`/api/v1/lorebooks/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  })
export const archiveLorebook = (id: string) =>
  jsonFetch<void>(`/api/v1/lorebooks/${id}/archive`, { method: 'POST' })
export const fetchPromptPreview = (sessionId: string, text = '') =>
  jsonFetch<PromptPreview>(`/api/v1/sessions/${sessionId}/prompt-preview`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
  })
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
export async function fetchLogs(lines = 200): Promise<string> {
  const response = await fetch(`/api/v1/logs?lines=${lines}`)
  if (!response.ok) throw new Error(`logs failed: ${response.status}`)
  return response.text()
}
export function chatWebSocketUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}/api/v1/chat/ws`
}
