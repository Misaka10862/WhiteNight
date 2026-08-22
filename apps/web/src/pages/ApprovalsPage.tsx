import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { approveRequest, fetchPendingApprovals, rejectRequest } from '../api'

export default function ApprovalsPage() {
  const queryClient = useQueryClient()
  const pending = useQuery({ queryKey: ['approvals'], queryFn: fetchPendingApprovals })
  const approve = useMutation({
    mutationFn: (item: { code: string; sessionId: string | null }) =>
      approveRequest(item.code, item.sessionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
      queryClient.invalidateQueries({ queryKey: ['messages'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
  const reject = useMutation({
    mutationFn: rejectRequest,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
      queryClient.invalidateQueries({ queryKey: ['messages'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })

  return (
    <section className="page" aria-label="审批">
      <h2>审批</h2>
      <p className="hint">
        风险说明、目标与参数摘要。审批编号一次性、短期、不可重放；会话授权在批准后生效。
      </p>
      <ul className="card-list">
        {(pending.data ?? []).map((item) => (
          <li key={item.id} className="card">
            <div>
              <strong>{item.tool_name}</strong> · risk={item.risk} · scope={item.scope}
            </div>
            <pre className="pre">{item.params_summary}</pre>
            <span className="muted">
              {item.created_at.slice(0, 19).replace('T', ' ')} 前有效
              {item.session_id ? ` · session=${item.session_id.slice(0, 8)}` : ''}
            </span>
            <div className="actions">
              <button onClick={() => approve.mutate({ code: item.code, sessionId: item.session_id })}>
                允许一次
              </button>
              {item.scope === 'session' && (
                <button onClick={() => approve.mutate({ code: item.code, sessionId: item.session_id })}>
                  允许本次会话
                </button>
              )}
              <button className="danger" onClick={() => reject.mutate(item.code)}>
                拒绝
              </button>
            </div>
          </li>
        ))}
        {pending.data?.length === 0 && <li className="empty">暂无待审批请求</li>}
      </ul>
    </section>
  )
}
