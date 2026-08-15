import { useQuery } from '@tanstack/react-query'
import { fetchStatus } from './api'

const phases = [
  ['0', '工程初始化'],
  ['1', '高风险能力验证'],
  ['2', '最小纵向链路'],
  ['3', '工具、文件与文档'],
  ['4', '长期记忆'],
  ['5', '路由与 Agent 委派'],
  ['6', '完整 WebUI'],
  ['7', '后台服务与主动行为'],
  ['8', 'QQ 私聊'],
  ['9', 'LoRA 人格固化'],
  ['10', '发布加固'],
] as const

export default function App() {
  const status = useQuery({ queryKey: ['status'], queryFn: fetchStatus })

  return (
    <main className="shell">
      <header className="topbar">
        <h1>WhiteNight <span className="nick">小白</span></h1>
        <p className="subtitle">本地优先的个人 AI 智能体 · 首版工作台</p>
      </header>

      <section className="status" aria-live="polite">
        {status.isPending && <p>正在连接本机服务…</p>}
        {status.isError && (
          <p className="error">
            无法连接后端（127.0.0.1:8765）。请先运行 <code>uv run whitenight</code>。
          </p>
        )}
        {status.data && (
          <dl>
            <div><dt>服务</dt><dd>{status.data.name} v{status.data.version}</dd></div>
            <div><dt>环境</dt><dd>{status.data.env}</dd></div>
            <div><dt>监听</dt><dd>{status.data.host}:{status.data.port}</dd></div>
            <div>
              <dt>数据库</dt>
              <dd>
                {status.data.database.url_backend} ·{' '}
                {status.data.database.reachable ? '可达' : '不可达'}
              </dd>
            </div>
          </dl>
        )}
      </section>

      <section className="chat">
        <p className="placeholder">聊天入口将在阶段 2 接入——这里保持安静，不给主人添乱。</p>
      </section>

      <footer className="phase-list">
        {phases.map(([no, label]) => (
          <span key={no} className={no === '0' ? 'active' : ''}>阶段 {no} · {label}</span>
        ))}
      </footer>
    </main>
  )
}
