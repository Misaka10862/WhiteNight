import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchModelConfig, fetchSystemHealth, updateModelKeepAlive } from '../api'

const KEEP_ALIVE_LABELS: Record<string, string> = {
  '-1': '常驻（最快，约 5.6GB 内存）',
  '5m': '5 分钟（Ollama 默认，闲置后卸载）',
  '30m': '30 分钟',
  '1h': '1 小时',
  '6h': '6 小时',
  '12h': '12 小时',
}

export default function ModelsPage() {
  const queryClient = useQueryClient()
  const health = useQuery({ queryKey: ['system-health'], queryFn: fetchSystemHealth, refetchInterval: 15000 })
  const modelConfig = useQuery({ queryKey: ['model-config'], queryFn: fetchModelConfig })
  const [keepAlive, setKeepAlive] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (modelConfig.data && !loaded) {
      setKeepAlive(modelConfig.data.ollama_keep_alive)
      setLoaded(true)
    }
  }, [modelConfig.data, loaded])

  const saveKeepAlive = useMutation({
    mutationFn: updateModelKeepAlive,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['model-config'] })
      queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })

  const options = modelConfig.data?.options ?? ['-1', '5m', '30m', '1h', '6h', '12h']

  return (
    <section className="page" aria-label="模型与 Agent">
      <h2>模型与 Agent</h2>
      <div className="split">
        <div className="panel">
          <h3>数据库</h3>
          <pre className="pre">{JSON.stringify(health.data?.database, null, 2)}</pre>
        </div>
        <div className="panel">
          <h3>模型</h3>
          <pre className="pre">{JSON.stringify(health.data?.model, null, 2)}</pre>
        </div>
      </div>
      <div className="panel">
        <h3>模型常驻</h3>
        <div className="inline-form">
          <label>
            Ollama 卸载策略
            <select
              value={keepAlive || (modelConfig.data?.ollama_keep_alive ?? '-1')}
              onChange={(event) => setKeepAlive(event.target.value)}
            >
              {options.map((option) => (
                <option key={option} value={option}>
                  {KEEP_ALIVE_LABELS[option] ?? option}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="actions">
          <button
            onClick={() => saveKeepAlive.mutate(keepAlive || '-1')}
            disabled={saveKeepAlive.isPending}
          >
            {saveKeepAlive.isPending ? '保存中…' : '保存并立即生效'}
          </button>
        </div>
        <p className="muted">
          常驻时闲置消息直接开始生成（无冷启动等待）；不常驻时模型会在闲置指定时间后卸载，
          下一条消息需要等待模型重新加载（约十几秒）。设置会写入本地配置，重启后保持。
        </p>
        {saveKeepAlive.isError && <div className="chat-error">保存失败：{String(saveKeepAlive.error)}</div>}
        {saveKeepAlive.isSuccess && <div className="chat-ok">已保存并立即生效。</div>}
      </div>
      <div className="panel">
        <h3>QQ / OneBot</h3>
        <pre className="pre">{JSON.stringify(health.data?.onebot ?? { enabled: false }, null, 2)}</pre>
      </div>
      <div className="panel">
        <h3>委派执行器</h3>
        <pre className="pre">{JSON.stringify(health.data?.delegates, null, 2)}</pre>
      </div>
      {health.isError && <div className="chat-error">无法获取系统状态</div>}
    </section>
  )
}
