import type { ChatEvent, DelegateEvent } from './api'

export interface SocketLike {
  onopen: (() => void) | null
  onmessage: ((event: { data: string }) => void) | null
  onerror: (() => void) | null
  onclose: (() => void) | null
  send: (payload: string) => void
  close: () => void
}

export interface ChatRun {
  requestId: string
  sessionId: string
  status: 'connecting' | 'running' | 'completed' | 'failed' | 'cancelled'
  text: string
  imageUrl: string | null
  attachmentNames: string[]
  streamingText: string
  taskEvent: DelegateEvent | null
  toolStatus: string | null
  error: string | null
}

interface StartInput {
  sessionId: string
  text: string
  imageUrl?: string | null
  attachmentIds?: string[]
  attachmentNames?: string[]
}

interface Dependencies {
  socket: () => SocketLike
  requestId: () => string
  refresh: (sessionId: string) => Promise<unknown>
  cancel: (requestId: string) => Promise<unknown>
}

export const isRunning = (run: ChatRun | undefined) => run?.status === 'connecting' || run?.status === 'running'
export const shouldSendOnEnter = (event: { key: string; shiftKey: boolean; isComposing?: boolean; keyCode?: number }) =>
  event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229

/** Owns request sockets independently of the selected page and session. */
export class ChatController {
  private runs = new Map<string, ChatRun>()
  private sockets = new Map<string, SocketLike>()
  private listeners = new Set<() => void>()
  private dependencies: Dependencies

  constructor(dependencies: Dependencies) { this.dependencies = dependencies }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  snapshot = (sessionId: string | null) => sessionId ? this.runs.get(sessionId) : undefined

  private update(sessionId: string, requestId: string, patch: Partial<ChatRun>) {
    const current = this.runs.get(sessionId)
    if (!current || current.requestId !== requestId) return false
    this.runs.set(sessionId, { ...current, ...patch })
    this.listeners.forEach(listener => listener())
    return true
  }

  start(input: StartInput) {
    if (isRunning(this.runs.get(input.sessionId))) return
    const { sessionId } = input
    const requestId = this.dependencies.requestId()
    this.runs.set(sessionId, {
      sessionId, requestId, status: 'connecting', text: input.text,
      imageUrl: input.imageUrl ?? null, attachmentNames: input.attachmentNames ?? [],
      streamingText: '', taskEvent: null, toolStatus: null, error: null,
    })
    this.listeners.forEach(listener => listener())
    let socket: SocketLike
    try { socket = this.dependencies.socket() }
    catch { void this.finish(sessionId, requestId, 'failed', '无法连接本机服务，请稍后重试'); return }
    this.sockets.set(requestId, socket)
    let terminal = false
    const finish = (status: ChatRun['status'], error: string | null = null) => {
      if (terminal) return
      terminal = true
      void this.finish(sessionId, requestId, status, error)
    }
    socket.onopen = () => {
      if (terminal || !this.sockets.has(requestId) || this.runs.get(sessionId)?.requestId !== requestId) return
      this.update(sessionId, requestId, { status: 'running' })
      try {
        socket.send(JSON.stringify({
          request_id: requestId, session_id: sessionId, text: input.text,
          image_data_url: input.imageUrl ?? null, attachment_ids: input.attachmentIds ?? [],
        }))
      } catch { finish('failed', '消息发送失败，请查看历史后重试') }
    }
    socket.onmessage = ({ data }) => {
      if (terminal || !this.sockets.has(requestId) || this.runs.get(sessionId)?.requestId !== requestId) return
      let message: ChatEvent
      try {
        const parsed = JSON.parse(data)
        if (!parsed || typeof parsed !== 'object' || typeof parsed.type !== 'string') throw new Error('Invalid event')
        if (parsed.type === 'chunk' && parsed.delta != null && typeof parsed.delta !== 'string') throw new Error('Invalid chunk')
        message = parsed as ChatEvent
      }
      catch { finish('failed', '收到无效消息，请核对历史'); return }
      if (message.type === 'start') this.update(sessionId, requestId, { status: 'running' })
      else if (message.type === 'chunk') {
        const current = this.runs.get(sessionId)!
        this.update(sessionId, requestId, { status: 'running', streamingText: current.streamingText + (message.delta ?? '') })
      } else if (message.type === 'task') this.update(sessionId, requestId, { taskEvent: message.extra?.delegate_event ?? null })
      else if (message.type === 'tool') {
        this.update(sessionId, requestId, { toolStatus: `${message.extra?.tool_name ?? '工具'} · ${message.extra?.status ?? 'running'}${message.extra?.message ? `：${message.extra.message}` : ''}` })
      } else if (message.type === 'approval') this.update(sessionId, requestId, { toolStatus: message.text ?? '等待审批' })
      else if (message.type === 'done') finish('completed')
      else if (message.type === 'error') finish('failed', message.message ?? '回复失败，请查看历史后重试')
    }
    socket.onerror = () => finish('failed', '连接失败，请核对历史；消息不会自动重复发送')
    socket.onclose = () => finish('failed', '连接中断，请核对历史；消息不会自动重复发送')
  }

  private async finish(sessionId: string, requestId: string, status: ChatRun['status'], error: string | null) {
    const socket = this.sockets.get(requestId)
    this.sockets.delete(requestId)
    if (socket) {
      socket.onclose = null
      socket.onerror = null
      socket.onmessage = null
      socket.onopen = null
      socket.close()
    }
    try { await this.dependencies.refresh(sessionId) }
    catch { error = error ?? '历史同步失败，请稍后刷新会话' }
    this.update(sessionId, requestId, {
      status, error, streamingText: '', taskEvent: null, toolStatus: null,
      ...(status === 'completed' || status === 'cancelled' ? { text: '', imageUrl: null, attachmentNames: [] } : {}),
    })
  }

  async cancel(sessionId: string) {
    const current = this.runs.get(sessionId)
    if (!current || !isRunning(current)) return
    try {
      if (current.status !== 'connecting') await this.dependencies.cancel(current.requestId)
      await this.finish(sessionId, current.requestId, 'cancelled', null)
    } catch {
      this.update(sessionId, current.requestId, { error: '停止请求失败，当前回复可能仍在生成，请重试' })
    }
  }
}
