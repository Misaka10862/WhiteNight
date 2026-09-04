import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { approveRequest, fetchPendingApprovals, rejectRequest } from '../api'
import { formatUtcTimestamp } from '../time'

export default function ApprovalsPage() {
  const queryClient = useQueryClient()
  const pending = useQuery({ queryKey: ['approvals'], queryFn: fetchPendingApprovals, refetchInterval: 5000 })
  const approve = useMutation({
    mutationFn: (item: { code: string; sessionId: string | null; scope: 'once' | 'session' }) =>
      approveRequest(item.code, item.sessionId, item.scope),
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
      {(pending.isError || approve.isError || reject.isError) && <p className="chat-error" role="alert">{String(pending.error ?? approve.error ?? reject.error)}</p>}
      {approve.isSuccess && <p role="status">{approve.data.reason}</p>}
      <ul className="card-list">
        {(pending.data ?? []).map((item) => (
          <li key={item.id} className="card">
            <div>
              <strong>{item.tool_name}</strong> · risk={item.risk} · scope={item.scope}
            </div>
            <pre className="pre">{item.params_summary}</pre>
            <span className="muted">
              {item.expires_at ? `${formatUtcTimestamp(item.expires_at)} 前有效` : '无到期时间'}
              {item.session_id ? ` · session=${item.session_id.slice(0, 8)}` : ''}
            </span>
            <div className="actions">
              <button disabled={approve.isPending || reject.isPending} onClick={() => approve.mutate({ code: item.code, sessionId: item.session_id, scope: 'once' })}>
                允许一次
              </button>
              {item.scope === 'session' && (
                <button disabled={approve.isPending || reject.isPending} onClick={() => approve.mutate({ code: item.code, sessionId: item.session_id, scope: 'session' })}>
                  允许本次会话
                </button>
              )}
              <button className="danger" disabled={approve.isPending || reject.isPending} onClick={() => reject.mutate(item.code)}>
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
