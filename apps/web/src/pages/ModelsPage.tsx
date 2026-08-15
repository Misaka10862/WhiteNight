import { useQuery } from '@tanstack/react-query'
import { fetchSystemHealth } from '../api'

export default function ModelsPage() {
  const health = useQuery({ queryKey: ['system-health'], queryFn: fetchSystemHealth, refetchInterval: 15000 })

  return (
    <section className="page" aria-label="模型与 Agent">
      <h2>模型与 Agent</h2>
      <div className="split">
        <div className="panel">
          <h3>数据库</h3>
          <pre className="pre">{JSON.stringify(health.data?.database, null, 2)}</pre>
        </div>
        <div className="panel">
          <h3>模型</h3>
          <pre className="pre">{JSON.stringify(health.data?.model, null, 2)}</pre>
        </div>
      </div>
      <div className="panel">
        <h3>委派执行器</h3>
        <pre className="pre">{JSON.stringify(health.data?.delegates, null, 2)}</pre>
      </div>
      {health.isError && <div className="chat-error">无法获取系统状态</div>}
    </section>
  )
}
