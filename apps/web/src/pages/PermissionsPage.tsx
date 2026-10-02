import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchFileAccess, probeFileAccess, fetchPolicyRules, fetchSessionGrants, revokeGrant } from '../api'

export default function PermissionsPage() {
  const queryClient = useQueryClient()
  const fileAccess = useQuery({ queryKey: ['file-access'], queryFn: fetchFileAccess })
  const probe = useMutation({ mutationFn: probeFileAccess })
  const rules = useQuery({ queryKey: ['policy-rules'], queryFn: fetchPolicyRules })
  const grants = useQuery({ queryKey: ['policy-grants'], queryFn: fetchSessionGrants })
  const revoke = useMutation({
    mutationFn: revokeGrant,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['policy-grants'] }),
  })

  return (
    <section className="page" aria-label="权限">
      <h2>权限</h2>
      <div className="panel">
        <h3>本机文件访问</h3>
        <p>{fileAccess.data?.note}</p>
        <p>授权应用：{fileAccess.data?.application}</p>
        {fileAccess.data && !fileAccess.data.dedicated_launcher && <p>当前仍使用旧启动入口，请安装 WhiteNight 专用入口。</p>}
        <div className="actions">
          <a href={fileAccess.data?.settings_url}>打开完全磁盘访问权限设置</a>
          <button disabled={probe.isPending} onClick={() => probe.mutate()}>授权后检测访问</button>
        </div>
        {probe.isError && <p role="alert">{String(probe.error)}</p>}
        <ul>{probe.data?.results.map(item => <li key={item.path}>{item.path}：{item.status === 'readable' ? '可读取' : item.message} {item.writable ? '· 可写权限' : ''}</li>)}</ul>
      </div>
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
