import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  chatWebSocketUrl,
  createSession,
  fetchMessages,
  fetchSessions,
  fetchStatus,
  type ChatEvent,
  type MessageRecord,
} from './api'

interface PendingUser {
  content: string
  imageUrl: string | null
}

export default function App() {
  const queryClient = useQueryClient()
  const [activeId, setActiveId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [pendingUser, setPendingUser] = useState<PendingUser | null>(null)
  const [chatError, setChatError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const autoCreated = useRef(false)

  const status = useQuery({ queryKey: ['status'], queryFn: fetchStatus })
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: fetchSessions })
  const messages = useQuery({
    queryKey: ['messages', activeId],
    queryFn: () => fetchMessages(activeId!),
    enabled: activeId !== null,
  })

  const newSession = useMutation({
    mutationFn: () => createSession(),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      setActiveId(session.id)
      setPendingUser(null)
      setStreamingText('')
    },
  })

  // 首次进入：有历史会话则恢复最近的；没有则静默新建。
  useEffect(() => {
    if (activeId !== null || !sessions.data || sessions.data.length === 0) return
    setActiveId(sessions.data[0].id)
  }, [activeId, sessions.data])

  useEffect(() => {
    if (
      autoCreated.current ||
      activeId !== null ||
      !sessions.data ||
      sessions.data.length !== 0
    ) {
      return
    }
    autoCreated.current = true
    newSession.mutate()
  }, [activeId, sessions.data, newSession])

  const send = () => {
    if (!activeId || streaming || (!draft.trim() && !imageUrl)) return
    setPendingUser({ content: draft, imageUrl })
    setStreamingText('')
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
      } else if (message.type === 'done') {
        setPendingUser(null)
        setStreamingText('')
        setStreaming(false)
        socket.close()
        queryClient.invalidateQueries({ queryKey: ['messages', activeId] })
        queryClient.invalidateQueries({ queryKey: ['sessions'] })
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
    <main className="shell">
      <header className="topbar">
        <h1>
          WhiteNight <span className="nick">小白</span>
        </h1>
        <p className="subtitle">
          {status.data ? `本机服务 v${status.data.version} · ${String(status.data.model['model'] ?? '模型状态未知')}` : '正在连接本机服务…'}
        </p>
      </header>

      <div className="workspace">
        <aside className="sessions">
          <button className="new-chat" onClick={() => newSession.mutate()} disabled={newSession.isPending}>
            新会话
          </button>
          {(sessions.data ?? []).map((session) => (
            <button
              key={session.id}
              className={session.id === activeId ? 'session active' : 'session'}
              onClick={() => setActiveId(session.id)}
            >
              <span className="session-title">{session.title}</span>
              <span className="session-count">{session.message_count}</span>
            </button>
          ))}
        </aside>

        <section className="chat">
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
              onChange={(event) => pickImage(event.target.files?.[0])}
            />
            <button type="button" className="attach" onClick={() => fileInput.current?.click()} title="发送图片">
              🖼
            </button>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="和小白说点什么…（Enter 发送，Shift+Enter 换行）"
              rows={1}
              disabled={disabled}
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
    </main>
  )
}

function MessageBubble({ message }: { message: MessageRecord }) {
  const isUser = message.role === 'user'
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
