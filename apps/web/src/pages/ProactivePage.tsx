import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchProactiveStatus,
  pauseProactive,
  resumeProactive,
  updateProactiveConfig,
  type ProactiveConfig,
} from '../api'

const DEFAULTS: ProactiveConfig = {
  enabled: false,
  expected_per_day: 1.5,
  quiet_start: '23:00',
  quiet_end: '08:00',
  suppress_minutes: 60,
  skip_grace_minutes: 45,
}

export default function ProactivePage() {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: ['proactive-status'], queryFn: fetchProactiveStatus })
  const [form, setForm] = useState<ProactiveConfig>(DEFAULTS)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (status.data && !loaded) {
      setForm(status.data.config)
      setLoaded(true)
    }
  }, [status.data, loaded])

  const save = useMutation({
    mutationFn: updateProactiveConfig,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['proactive-status'] }),
  })
  const pause = useMutation({
    mutationFn: () => pauseProactive(null),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['proactive-status'] }),
  })
  const resume = useMutation({
    mutationFn: resumeProactive,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['proactive-status'] }),
  })

  const data = status.data

  return (
    <section className="page" aria-label="主动消息">
      <h2>主动消息</h2>
      <p className="hint">
        主动消息按泊松过程生成，在静默时段和最近聊天抑制规则之外发送。当前投递渠道和 QQ
        连接状态会显示在下方；发送审计只保留元数据，不保存消息正文。
      </p>

      <div className="panel">
        <label className="row-label">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
          />
          启用主动消息
        </label>
        <div className="inline-form">
          <label>
            每日期望次数
            <input
              type="number"
              min={0.1}
              max={6}
              step={0.1}
              value={form.expected_per_day}
              onChange={(event) => setForm({ ...form, expected_per_day: Number(event.target.value) })}
            />
          </label>
          <label>
            静默开始
            <input value={form.quiet_start} onChange={(event) => setForm({ ...form, quiet_start: event.target.value })} />
          </label>
          <label>
            静默结束
            <input value={form.quiet_end} onChange={(event) => setForm({ ...form, quiet_end: event.target.value })} />
          </label>
          <label>
            活动抑制(分钟)
            <input
              type="number"
              min={0}
              max={480}
              value={form.suppress_minutes}
              onChange={(event) => setForm({ ...form, suppress_minutes: Number(event.target.value) })}
            />
          </label>
          <label>
            过期宽限(分钟)
            <input
              type="number"
              min={5}
              max={240}
              value={form.skip_grace_minutes}
              onChange={(event) => setForm({ ...form, skip_grace_minutes: Number(event.target.value) })}
            />
          </label>
        </div>
        <div className="actions">
          <button onClick={() => save.mutate(form)} disabled={save.isPending}>
            保存配置
          </button>
          {data?.paused ? (
            <button onClick={() => resume.mutate()}>恢复</button>
          ) : (
            <button onClick={() => pause.mutate()}>暂停</button>
          )}
        </div>
      </div>

      <div className="panel">
        <h3>状态</h3>
        <pre className="pre">
          {JSON.stringify(
            {
              paused: data?.paused,
              paused_until: data?.paused_until,
              last_activity_at: data?.last_activity_at,
              last_sent_at: data?.last_sent_at,
              next_candidate_at: data?.next_candidate_at,
              delivery: data?.delivery,
            },
            null,
            2,
          )}
        </pre>
        <p className="muted">
          投递：{data?.delivery?.active_sender ?? '未知'}
          {data?.delivery?.target_user_id ? ` → QQ ${data.delivery.target_user_id}` : ''}
          {data?.delivery?.onebot_reachable !== null && data?.delivery?.onebot_reachable !== undefined
            ? ` · OneBot：${data.delivery.onebot_reachable ? '在线' : '离线'}`
            : ''}
          {data?.delivery?.available === false ? `（不可用：${data.delivery.reason}）` : ''}
        </p>
        <p className="muted">睡眠/断网导致候选过期超过宽限期时不补发，直接重新调度。</p>
      </div>
    </section>
  )
}
