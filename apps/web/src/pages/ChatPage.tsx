import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  chatWebSocketUrl,
  deleteSession,
  exportSession,
  fetchMessages,
  renameSession,
  type ChatEvent,
  type CharacterRecord,
  type DelegateEvent,
  type MessageRecord,
  type SessionSummary,
} from '../api'

interface PendingUser {
  content: string
  imageUrl: string | null
}

export default function ChatPage({
  sessions,
  activeId,
  onSelectSession,
  onNewSession,
  characters,
}: {
  sessions: SessionSummary[]
  activeId: string | null
  onSelectSession: (id: string) => void
  onNewSession: (characterId: string, greetingIndex?: number) => void
  characters: CharacterRecord[]
}) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [pendingUser, setPendingUser] = useState<PendingUser | null>(null)
  const [taskEvent, setTaskEvent] = useState<DelegateEvent | null>(null)
  const [toolStatus, setToolStatus] = useState<string | null>(null)
  const [chatError, setChatError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const activeSession = sessions.find((session) => session.id === activeId) ?? null
  const [newCharacterId, setNewCharacterId] = useState('')
  const [greeting, setGreeting] = useState('0')
  useEffect(() => {
    const fallback = activeSession?.character_id ?? characters[0]?.id ?? ''
    setNewCharacterId(fallback)
    setGreeting('0')
  }, [activeSession?.character_id, characters])
  const newCharacter = characters.find((item) => item.id === newCharacterId)
  const greetings = newCharacter ? [newCharacter.card.data.first_mes, ...newCharacter.card.data.alternate_greetings] : []

  const messages = useQuery({
    queryKey: ['messages', activeId],
    queryFn: () => fetchMessages(activeId!),
    enabled: activeId !== null,
  })

  const send = () => {
    if (!activeId || streaming || (!draft.trim() && !imageUrl)) return
    setPendingUser({ content: draft, imageUrl })
    setStreamingText('')
    setTaskEvent(null)
    setToolStatus(null)
    setStreaming(true)
    setChatError(null)

    const socket = new WebSocket(chatWebSocketUrl())
    const payload = { session_id: activeId, text: draft, image_data_url: imageUrl }
    setDraft('')
    setImageUrl(null)
    if (fileInput.current) fileInput.current.value = ''

    socket.onopen = () => socket.send(JSON.stringify(payload))
    socket.onmessage = (event: MessageEvent<string>) => {
      const message = JSON.parse(event.data) as ChatEvent
      if (message.type === 'start') {
        setPendingUser(null)
      } else if (message.type === 'chunk' && message.delta) {
        setStreamingText((previous) => previous + message.delta)
      } else if (message.type === 'task' && message.extra?.delegate_event) {
        setTaskEvent(message.extra.delegate_event)
      } else if (message.type === 'tool') {
        const name = message.extra?.tool_name ?? '工具'
        const status = message.extra?.status ?? 'running'
        setToolStatus(`${name} · ${status}${message.extra?.message ? `：${message.extra.message}` : ''}`)
      } else if (message.type === 'approval') {
        setToolStatus(message.text ?? '操作等待审批')
      } else if (message.type === 'done') {
        setPendingUser(null)
        setStreamingText('')
        setTaskEvent(null)
        setToolStatus(null)
        setStreaming(false)
        socket.close()
        queryClient.invalidateQueries({ queryKey: ['messages', activeId] })
        queryClient.invalidateQueries({ queryKey: ['sessions'] })
        queryClient.invalidateQueries({ queryKey: ['tasks'] })
      } else if (message.type === 'error') {
        setPendingUser(null)
        setStreamingText('')
        setStreaming(false)
        setChatError(message.message ?? '发生未知错误')
        socket.close()
        queryClient.invalidateQueries({ queryKey: ['messages', activeId] })
        queryClient.invalidateQueries({ queryKey: ['sessions'] })
      }
    }
    socket.onerror = () => {
      setStreaming(false)
      setChatError('无法连接本机服务，请确认后端已启动（uv run whitenight）')
    }
    socket.onclose = () => setStreaming(false)
  }

  const pickImage = (file: File | undefined) => {
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setChatError('只支持图片附件')
      return
    }
    if (file.size > 8 * 1024 * 1024) {
      setChatError('图片不能超过 8 MiB')
      return
    }
    const reader = new FileReader()
    reader.onload = () => setImageUrl(String(reader.result))
    reader.readAsDataURL(file)
  }

  const shownMessages = messages.data ?? []
  const disabled = streaming || !activeId

  return (
    <div className="chat-layout">
      <aside className="sessions">
        <button className="new-chat" onClick={() => newCharacterId && onNewSession(newCharacterId, greeting === 'none' ? undefined : Number(greeting))}>
          新会话
        </button>
        {(sessions ?? []).map((session) => (
          <button
            key={session.id}
            className={session.id === activeId ? 'session active' : 'session'}
            onClick={() => onSelectSession(session.id)}
            title={session.title}
          >
            <span className="session-title">{session.title}<small>{session.character_name ?? '角色未知'}</small></span>
            <span className="session-count">{session.message_count}</span>
          </button>
        ))}
      </aside>

      <section className="chat" aria-label="聊天">
        <div className="chat-context-bar">
          <span><strong>{activeSession?.character_name ?? '未选择角色'}</strong><small>会话角色已锁定</small></span>
          <label>新角色<select value={newCharacterId} onChange={(event) => { setNewCharacterId(event.target.value); setGreeting('0') }}>{characters.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}</select></label>
          <label>开场<select value={greeting} onChange={(event) => setGreeting(event.target.value)}><option value="none">无开场</option>{greetings.map((item, index) => <option key={`${index}-${item.slice(0, 12)}`} value={index}>{item || '空开场'}</option>)}</select></label>
          <button onClick={() => newCharacterId && onNewSession(newCharacterId, greeting === 'none' ? undefined : Number(greeting))}>新建</button>
        </div>
        <div className="messages">
          {shownMessages.map((message: MessageRecord) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {pendingUser && (
            <div className="row user">
              <div className="bubble">
                {pendingUser.imageUrl && (
                  <img className="message-image" src={pendingUser.imageUrl} alt="附件图片" />
                )}
                {pendingUser.content && <p>{pendingUser.content}</p>}
              </div>
            </div>
          )}
          {taskEvent && (
            <div className="row assistant">
              <div className="bubble task-bubble" role="status">
                <strong>任务 · {taskEvent.executor}</strong>
                <p>
                  {taskEvent.label}
                  {taskEvent.detail ? `：${taskEvent.detail}` : ''}
                </p>
                {taskEvent.type === 'progress' && <progress value={taskEvent.progress ?? undefined} />}
              </div>
            </div>
          )}
          {toolStatus && (
            <div className="row assistant">
              <div className="bubble task-bubble" role="status">
                <strong>工具</strong>
                <p>{toolStatus}</p>
              </div>
            </div>
          )}
          {streamingText && (
            <div className="row assistant">
              <div className="bubble">
                {streamingText}
                <span className="cursor">▍</span>
              </div>
            </div>
          )}
        </div>

        {chatError && (
          <div className="chat-error" role="alert">
            {chatError}
          </div>
        )}

        {imageUrl && (
          <div className="preview">
            <img src={imageUrl} alt="待发送图片" />
            <button onClick={() => setImageUrl(null)}>移除</button>
          </div>
        )}

        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault()
            send()
          }}
        >
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            hidden
            aria-label="选择图片"
            onChange={(event) => pickImage(event.target.files?.[0])}
          />
          <button type="button" className="attach" onClick={() => fileInput.current?.click()} title="发送图片">
            🖼
          </button>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={`和${activeSession?.character_name ?? '当前角色'}说点什么…`}
            rows={1}
            disabled={disabled}
            aria-label="聊天输入"
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
          />
          <button type="submit" className="send" disabled={disabled}>
            发送
          </button>
        </form>
      </section>
    </div>
  )
}

function MessageBubble({ message }: { message: MessageRecord }) {
  const isUser = message.role === 'user'
  if (message.role === 'tool') {
    return (
      <div className="row assistant">
        <div className="bubble task-bubble">
          <strong>工具结果</strong>
          <p>{message.content.slice(0, 240)}</p>
        </div>
      </div>
    )
  }
  return (
    <div className={isUser ? 'row user' : 'row assistant'}>
      <div className="bubble">
        {message.image_data_url && (
          <img className="message-image" src={message.image_data_url} alt="附件图片" />
        )}
        {message.content && <p>{message.content}</p>}
        {!message.content && !message.image_data_url && <p className="empty">（空消息）</p>}
      </div>
    </div>
  )
}

export function SessionsPage({
  sessions,
  activeId,
  onSelectSession,
}: {
  sessions: SessionSummary[]
  activeId: string | null
  onSelectSession: (id: string) => void
}) {
  const queryClient = useQueryClient()
  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => renameSession(id, title),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sessions'] }),
  })
  const remove = useMutation({
    mutationFn: deleteSession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['messages'] })
    },
  })

  return (
    <section className="page" aria-label="会话管理">
      <h2>会话管理</h2>
      <p className="hint">所有入口共享同一会话。删除立即移除且不记录正文审计。</p>
      <ul className="card-list">
        {sessions.map((session) => (
          <li key={session.id} className={session.id === activeId ? 'card active' : 'card'}>
            <button className="link" onClick={() => onSelectSession(session.id)}>
              {session.title}
            </button>
            <span className="muted">{session.message_count} 条 · {session.updated_at.slice(0, 16).replace('T', ' ')}</span>
            <div className="actions">
              <button
                onClick={() => {
                  const title = window.prompt('新标题', session.title)
                  if (title) rename.mutate({ id: session.id, title })
                }}
              >
                重命名
              </button>
              <button onClick={() => exportSession(session.id, 'markdown')}>导出</button>
              <button
                className="danger"
                onClick={() => {
                  if (window.confirm(`删除会话「${session.title}」？此操作立即生效。`)) {
                    remove.mutate(session.id)
                  }
                }}
              >
                删除
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
