import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createSession, fetchSessions, fetchStatus } from './api'
import ChatPage, { SessionsPage } from './pages/ChatPage'
import MemoryPage from './pages/MemoryPage'
import TasksPage from './pages/TasksPage'
import ApprovalsPage from './pages/ApprovalsPage'
import PermissionsPage from './pages/PermissionsPage'
import ModelsPage from './pages/ModelsPage'
import RulesPage from './pages/RulesPage'
import PlaceholderPage from './pages/PlaceholderPage'

type Tab = 'chat' | 'sessions' | 'memory' | 'tasks' | 'approvals' | 'permissions' | 'models' | 'rules' | 'active' | 'logs' | 'backup'

const TABS: { id: Tab; label: string; title: string }[] = [
  { id: 'chat', label: '聊天', title: '聊天' },
  { id: 'sessions', label: '会话', title: '会话管理' },
  { id: 'memory', label: '记忆', title: '长期记忆' },
  { id: 'tasks', label: '任务', title: '任务' },
  { id: 'approvals', label: '审批', title: '审批' },
  { id: 'permissions', label: '权限', title: '权限' },
  { id: 'models', label: '模型', title: '模型与 Agent' },
  { id: 'rules', label: '约束', title: '临时约束' },
  { id: 'active', label: '主动', title: '主动消息' },
  { id: 'logs', label: '日志', title: '运行日志' },
  { id: 'backup', label: '备份', title: '备份与恢复' },
]

export default function App() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('chat')
  const [activeId, setActiveId] = useState<string | null>(null)
  const [navOpen, setNavOpen] = useState(false)

  const status = useQuery({ queryKey: ['status'], queryFn: fetchStatus })
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: fetchSessions })
  const newSession = useMutation({
    mutationFn: () => createSession(),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      setActiveId(session.id)
      setTab('chat')
    },
  })

  // 首次进入：恢复最近会话；没有则静默新建。
  useEffect(() => {
    if (activeId !== null || !sessions.data || sessions.data.length === 0) return
    setActiveId(sessions.data[0].id)
  }, [activeId, sessions.data])

  useEffect(() => {
    if (activeId !== null || !sessions.data || sessions.data.length !== 0 || newSession.isPending) return
    newSession.mutate()
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
          {tab === 'chat' && (
            <ChatPage
              sessions={sessions.data ?? []}
              activeId={activeId}
              onSelectSession={(id) => setActiveId(id)}
              onNewSession={() => newSession.mutate()}
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
          {tab === 'memory' && <MemoryPage />}
          {tab === 'tasks' && <TasksPage sessionId={activeId} />}
          {tab === 'approvals' && <ApprovalsPage />}
          {tab === 'permissions' && <PermissionsPage />}
          {tab === 'models' && <ModelsPage />}
          {tab === 'rules' && <RulesPage />}
          {tab === 'active' && (
            <PlaceholderPage title="主动消息" description="泊松调度、静默时段与暂停在阶段 7 接入。" />
          )}
          {tab === 'logs' && (
            <PlaceholderPage title="运行日志" description="日志查看与脱敏导出随诊断工具在阶段 10 接入。" />
          )}
          {tab === 'backup' && (
            <PlaceholderPage title="备份与恢复" description="加密全量/增量备份与恢复演练在阶段 10 接入。" />
          )}
        </div>
      </div>
    </main>
  )
}
