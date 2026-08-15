import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchPolicyRules, fetchSessionGrants, revokeGrant } from '../api'

export default function PermissionsPage() {
  const queryClient = useQueryClient()
  const rules = useQuery({ queryKey: ['policy-rules'], queryFn: fetchPolicyRules })
  const grants = useQuery({ queryKey: ['policy-grants'], queryFn: fetchSessionGrants })
  const revoke = useMutation({
    mutationFn: revokeGrant,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['policy-grants'] }),
  })

  return (
    <section className="page" aria-label="权限">
      <h2>权限</h2>
      <div className="split">
        <div className="panel">
          <h3>工具类别授权</h3>
          <ul className="card-list">
            {(rules.data ?? []).map((rule) => (
              <li key={rule.tool} className="card">
                <code>{rule.tool}</code> → <strong>{rule.risk}</strong>
              </li>
            ))}
          </ul>
        </div>
        <div className="panel">
          <h3>会话授权（可撤销）</h3>
          <ul className="card-list">
            {(grants.data ?? []).map((grant) => (
              <li key={grant.id} className="card">
                <code>{grant.tool_name}</code> · session={grant.session_id.slice(0, 8)}
                <span className="muted"> · {grant.created_at.slice(0, 19).replace('T', ' ')}</span>
                <div className="actions">
                  <button className="danger" onClick={() => revoke.mutate(grant.id)}>
                    撤销
                  </button>
                </div>
              </li>
            ))}
            {grants.data?.length === 0 && <li className="empty">暂无会话授权</li>}
          </ul>
        </div>
      </div>
    </section>
  )
}
