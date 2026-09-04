import { useState } from 'react'
import { formatUtcTimestamp } from '../time'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createBackup, downloadBackup, fetchBackups, previewBackup, verifyBackup } from '../api'

export default function BackupPage() {
  const queryClient = useQueryClient()
  const backups = useQuery({ queryKey: ['backups'], queryFn: fetchBackups })
  const [details, setDetails] = useState<{ title: string; data: Record<string, unknown> } | null>(null)
  const create = useMutation({ mutationFn: createBackup, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['backups'] }) })
  const verify = useMutation({ mutationFn: verifyBackup, onSuccess: (data) => setDetails({ title: '验证结果', data }) })
  const preview = useMutation({ mutationFn: previewBackup, onSuccess: (data) => setDetails({ title: '恢复预览', data }) })
  const download = useMutation({ mutationFn: downloadBackup })
  const error = backups.error ?? create.error ?? verify.error ?? preview.error ?? download.error
  const busy = create.isPending || verify.isPending || preview.isPending
  const counts = details?.data.counts as Record<string, number> | undefined
  const resources = details?.data.resources as Record<string, number> | undefined
  const summary: [string, number | undefined][] = [
    ['会话', counts?.sessions], ['消息', counts?.messages],
    ['事实记忆', counts?.profile_facts], ['情景记忆', counts?.episodic_memories],
    ['角色', counts?.character_profiles], ['任务', counts?.agent_tasks],
    ['聊天附件', resources?.attachments], ['QQ 文件', resources?.qq_files],
    ['角色资源', resources?.characters], ['表情资源', resources?.stickers],
  ]

  return <section className="page" aria-label="备份与恢复">
    <h2>备份与恢复</h2>
    <p className="hint">加密备份包含数据库、聊天附件、QQ 文件、角色资源和表情。恢复密钥保存在本机 Keychain。</p>
    <div className="actions"><button disabled={busy} onClick={() => create.mutate()}>{create.isPending ? '创建中…' : '创建全量备份'}</button></div>
    {error && <p className="chat-error" role="alert">{String(error)}</p>}
    {create.isSuccess && <p className="chat-ok" role="status">备份已创建。</p>}
    <ul className="card-list">
      {(backups.data ?? []).map(backup => <li className="card" key={backup.id}>
        <strong>{backup.id}</strong>
        <p className="muted">{formatUtcTimestamp(backup.created_at)} · {(backup.size / 1024 / 1024).toFixed(2)} MiB</p>
        <div className="actions">
          <button disabled={busy} onClick={() => verify.mutate(backup.id)}>验证</button>
          <button disabled={busy} onClick={() => preview.mutate(backup.id)}>恢复预览</button>
          <button disabled={download.isPending} onClick={() => download.mutate(backup.id)}>下载</button>
        </div>
      </li>)}
      {backups.data?.length === 0 && <li className="empty">尚无备份</li>}
    </ul>
    {details && <div className="panel"><h3>{details.title}</h3>
      <p>备份完整性校验通过。</p>
      <p className="muted">数据库类型：{details.data.backend === 'sqlcipher' ? 'SQLCipher' : 'SQLite'}</p>
      <dl className="backup-summary">{summary.filter(([, value]) => typeof value === 'number').map(([label, value]) =>
        <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    </div>}
    <div className="panel"><h3>离线恢复</h3>
      <p>先验证备份，停止 WhiteNight 后运行恢复命令。恢复会保留当前数据库和文件的旧代际；重启服务时会检查并恢复未完成的操作。</p>
      <pre className="pre">{'uv run scripts/backup.py restore --input <备份文件路径>'}</pre>
      <p className="muted">在其他电脑恢复前，需要先将独立恢复密钥导入该电脑的 Keychain。恢复支持备份原有的数据库类型。</p>
    </div>
  </section>
}
