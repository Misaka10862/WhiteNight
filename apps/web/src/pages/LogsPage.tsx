import { useQuery } from '@tanstack/react-query'
import { fetchLogs } from '../api'

export default function LogsPage() {
  const logs = useQuery({
    queryKey: ['logs'],
    queryFn: () => fetchLogs(200),
    refetchInterval: 5000,
  })

  return (
    <section className="page" aria-label="运行日志">
      <h2>运行日志</h2>
      <p className="hint">最近 200 行（写入时已脱敏）。完整文件在 data/logs/whitenight.log。</p>
      <pre className="pre log-view">{logs.data ?? '（暂无日志）'}</pre>
      {logs.isError && <div className="chat-error">日志读取失败</div>}
    </section>
  )
}
