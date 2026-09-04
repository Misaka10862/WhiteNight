import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { abortTask, fetchTasks, retryTask } from '../api'

export default function TasksPage({ sessionId }: { sessionId?: string | null }) {
  const queryClient = useQueryClient()
  const tasks = useQuery({ queryKey: ['tasks', sessionId], queryFn: () => fetchTasks(sessionId ?? undefined), refetchInterval: 3000 })
  const abort = useMutation({
    mutationFn: abortTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  })
  const retry = useMutation({ mutationFn: retryTask, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }) })

  return (
    <section className="page" aria-label="任务">
      <h2>任务</h2>
      <p className="hint">任务状态每 3 秒更新；明确失败的只读任务可重试，其他任务需先核验执行结果。</p>
      {(tasks.isError || abort.isError || retry.isError) && <p className="chat-error" role="alert">{String(tasks.error ?? abort.error ?? retry.error)}</p>}
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
                <button className="danger" disabled={abort.isPending} onClick={() => abort.mutate(task.id)}>
                  中止
                </button>
              )}
              {task.status === 'failed' && task.risk === 'read_only' && <button disabled={retry.isPending} onClick={() => retry.mutate(task.id)}>重试</button>}
            </div>
          </li>
        ))}
        {tasks.data?.length === 0 && <li className="empty">暂无任务</li>}
      </ul>
    </section>
  )
}
