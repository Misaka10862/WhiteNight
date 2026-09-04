import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { cancelChat, chatWebSocketUrl, createSession, fetchCharacters, fetchSessions, fetchStatus } from './api'
import { ChatController, type SocketLike } from './chatController'
import ChatPage, { SessionsPage } from './pages/ChatPage'
import MemoryPage from './pages/MemoryPage'
import TasksPage from './pages/TasksPage'
import ApprovalsPage from './pages/ApprovalsPage'
import PermissionsPage from './pages/PermissionsPage'
import ModelsPage from './pages/ModelsPage'
import ProactivePage from './pages/ProactivePage'
import LogsPage from './pages/LogsPage'
import BackupPage from './pages/BackupPage'
import CharactersPage from './pages/CharactersPage'

type Tab = 'chat' | 'sessions' | 'characters' | 'memory' | 'tasks' | 'approvals' | 'permissions' | 'models' | 'active' | 'logs' | 'backup'

const TABS: { id: Tab; label: string; title: string }[] = [
  { id: 'chat', label: '聊天', title: '聊天' },
  { id: 'sessions', label: '会话', title: '会话管理' },
  { id: 'characters', label: '角色', title: '角色与编排' },
  { id: 'memory', label: '记忆', title: '长期记忆' },
  { id: 'tasks', label: '任务', title: '任务' },
  { id: 'approvals', label: '审批', title: '审批' },
  { id: 'permissions', label: '权限', title: '权限' },
  { id: 'models', label: '模型', title: '模型与 Agent' },
  { id: 'active', label: '主动', title: '主动消息' },
  { id: 'logs', label: '日志', title: '运行日志' },
  { id: 'backup', label: '备份', title: '备份与恢复' },
]

export default function App() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('chat')
  const [activeId, setActiveId] = useState<string | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [chatController] = useState(() => new ChatController({
    socket: () => new WebSocket(chatWebSocketUrl()) as unknown as SocketLike,
    requestId: () => crypto.randomUUID(),
    cancel: cancelChat,
    refresh: async (sessionId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['messages', sessionId] }),
        queryClient.invalidateQueries({ queryKey: ['sessions'] }),
        queryClient.invalidateQueries({ queryKey: ['tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['approvals'] }),
      ])
    },
  }))

  const status = useQuery({ queryKey: ['status'], queryFn: fetchStatus })
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: fetchSessions })
  const characters = useQuery({ queryKey: ['characters'], queryFn: fetchCharacters })
  const newSession = useMutation({
    mutationFn: (payload?: { character_id?: string; greeting_index?: number }) => createSession(payload),
    onSuccess: (session) => {
      queryClient.setQueryData(['sessions'], (previous: typeof sessions.data) => [session, ...(previous ?? []).filter(item => item.id !== session.id)])
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      setActiveId(session.id)
      setTab('chat')
    },
  })

  // 首次进入：恢复最近会话；没有则静默新建。
  useEffect(() => {
    if (!sessions.data || (activeId !== null && sessions.data.some(session => session.id === activeId))) return
    setActiveId(sessions.data[0]?.id ?? null)
  }, [activeId, sessions.data])

  useEffect(() => {
    if (activeId !== null || !sessions.data || sessions.data.length !== 0 || newSession.isPending || newSession.isError) return
    newSession.mutate(undefined)
  }, [activeId, sessions.data, newSession])

  return (
    <main className="shell">
      <header className="topbar">
        <button className="nav-toggle" aria-label="打开导航" onClick={() => setNavOpen((open) => !open)}>
          ☰
        </button>
        <h1>
          WhiteNight <span className="nick">小白</span>
        </h1>
        <p className="subtitle">
          {status.data
            ? `本机服务 v${status.data.version} · ${String(status.data.model['model'] ?? '模型状态未知')}`
            : '正在连接本机服务…'}
        </p>
      </header>

      <div className="workspace">
        <nav className={navOpen ? 'nav open' : 'nav'} aria-label="主导航">
          {TABS.map((item) => (
            <button
              key={item.id}
              className={tab === item.id ? 'nav-item active' : 'nav-item'}
              onClick={() => {
                setTab(item.id)
                setNavOpen(false)
              }}
              title={item.title}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="content" role="main">
          {(sessions.isError || newSession.isError) && <div className="chat-error" role="alert">{String(sessions.error ?? newSession.error)}</div>}
          {tab === 'chat' && (
            <ChatPage
              sessions={sessions.data ?? []}
              activeId={activeId}
              controller={chatController}
              onSelectSession={(id) => setActiveId(id)}
              characters={characters.data ?? []}
              onNewSession={(characterId, greetingIndex) => newSession.mutate({
                character_id: characterId,
                ...(greetingIndex === undefined ? {} : { greeting_index: greetingIndex }),
              })}
            />
          )}
          {tab === 'sessions' && (
            <SessionsPage
              sessions={sessions.data ?? []}
              activeId={activeId}
              onSelectSession={(id) => {
                setActiveId(id)
                setTab('chat')
              }}
            />
          )}
          {tab === 'characters' && <CharactersPage sessionId={activeId} />}
          {tab === 'memory' && <MemoryPage characterId={sessions.data?.find((item) => item.id === activeId)?.character_id ?? null} />}
          {tab === 'tasks' && <TasksPage sessionId={activeId} />}
          {tab === 'approvals' && <ApprovalsPage />}
          {tab === 'permissions' && <PermissionsPage />}
          {tab === 'models' && <ModelsPage />}
          {tab === 'active' && <ProactivePage />}
          {tab === 'logs' && <LogsPage />}
          {tab === 'backup' && <BackupPage />}
        </div>
      </div>
    </main>
  )
}
