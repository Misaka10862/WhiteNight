import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { approveBatch, approveRequest, fetchPendingApprovals, fetchSessions, rejectRequest } from '../api'
import { formatUtcTimestamp } from '../time'

export default function ApprovalsPage() {
  const queryClient = useQueryClient()
  const [sessionId, setSessionId] = useState('')
  const conversationList = useQuery({ queryKey: ['sessions'], queryFn: fetchSessions })
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

  const batch = useMutation({
    mutationFn: (selection: { sessionId: string; codes: string[] }) => approveBatch(selection.sessionId, selection.codes),
    onSuccess: () => {
      for (const key of ['approvals', 'messages', 'sessions', 'tasks'])
        queryClient.invalidateQueries({ queryKey: [key] })
    },
  })
  const sessions = [...new Set((pending.data ?? []).filter(item => item.channel === 'web').map(item => item.session_id).filter((id): id is string => Boolean(id)))]
  const selectedSessionId = sessionId || (sessions.length === 1 ? sessions[0] : '')
  const selected = (pending.data ?? []).filter(item => item.channel === 'web' && item.session_id === selectedSessionId)

  return (
    <section className="page" aria-label="审批">
      <h2>审批</h2>
      <p className="hint">
        风险说明、目标与参数摘要。审批编号一次性、短期、不可重放；会话授权在批准后生效。
      </p>
      {(pending.isError || approve.isError || reject.isError) && <p className="chat-error" role="alert">{String(pending.error ?? approve.error ?? reject.error)}</p>}
      {approve.isSuccess && <p role="status">{approve.data.reason}</p>}
      <div className="actions">
        <select aria-label="批量审批会话" value={selectedSessionId} disabled={batch.isPending} onChange={event => setSessionId(event.target.value)}>
          <option value="">选择对话</option>
          {sessions.map(id => <option key={id} value={id}>{conversationList.data?.find(session => session.id === id)?.title || id.slice(0, 8)}</option>)}
        </select>
        <button disabled={!selected.length || batch.isPending || approve.isPending || reject.isPending}
          onClick={() => batch.mutate({ sessionId: selectedSessionId, codes: selected.map(item => item.code) })}>全部同意（{selected.length}）</button>
      </div>
      {batch.isError && <p role="alert">{String(batch.error)}</p>}
      {batch.isSuccess && <pre role="status" className="pre">{batch.data.reason}</pre>}
      <ul className="card-list">
        {(pending.data ?? []).map((item) => (
          <li key={item.id} className="card">
            <div>
              <strong>{item.tool_name}</strong> · risk={item.risk} · scope={item.scope}
            </div>
            <p>编号：{item.code}</p>
            <pre className="pre">{item.params_summary}</pre>
            {item.channel !== 'web' && <p>请在原对话中回复“全部同意”或审批编号。</p>}
            <span className="muted">
              {item.expires_at ? `${formatUtcTimestamp(item.expires_at)} 前有效` : '无到期时间'}
              {item.session_id ? ` · session=${item.session_id.slice(0, 8)}` : ''}
            </span>
            <div className="actions">
              <button disabled={batch.isPending || approve.isPending || reject.isPending || item.channel !== 'web'} onClick={() => approve.mutate({ code: item.code, sessionId: item.session_id, scope: 'once' })}>
                允许一次
              </button>
              {item.scope === 'session' && (
                <button disabled={batch.isPending || approve.isPending || reject.isPending || item.channel !== 'web'} onClick={() => approve.mutate({ code: item.code, sessionId: item.session_id, scope: 'session' })}>
                  允许本次会话
                </button>
              )}
              <button className="danger" disabled={batch.isPending || approve.isPending || reject.isPending || item.channel !== 'web'} onClick={() => reject.mutate(item.code)}>
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
