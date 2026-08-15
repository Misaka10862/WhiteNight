import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { abortTask, fetchTasks } from '../api'

export default function TasksPage({ sessionId }: { sessionId?: string | null }) {
  const queryClient = useQueryClient()
  const tasks = useQuery({ queryKey: ['tasks', sessionId], queryFn: () => fetchTasks(sessionId ?? undefined) })
  const abort = useMutation({
    mutationFn: abortTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  })

  return (
    <section className="page" aria-label="任务">
      <h2>任务</h2>
      <p className="hint">Hermes/Codex 任务的执行者、状态、产物与错误；失败可安全重试。</p>
      <ul className="card-list">
        {(tasks.data ?? []).map((task) => (
          <li key={task.id} className="card">
            <div>
              <strong>[{task.executor}]</strong> {task.category} ·{' '}
              <span className={`status status-${task.status}`}>{task.status}</span>
            </div>
            <p className="prompt">{task.prompt}</p>
            <span className="muted">
              risk={task.risk} · attempts={task.attempts}
              {task.thread_id ? ` · thread=${task.thread_id}` : ''}
            </span>
            {task.error && <p className="chat-error">{task.error}</p>}
            {task.artifacts.length > 0 && <pre className="pre">{JSON.stringify(task.artifacts, null, 2)}</pre>}
            <div className="actions">
              {(task.status === 'running' || task.status === 'queued') && (
                <button className="danger" onClick={() => abort.mutate(task.id)}>
                  中止
                </button>
              )}
            </div>
          </li>
        ))}
        {tasks.data?.length === 0 && <li className="empty">暂无任务</li>}
      </ul>
    </section>
  )
}
