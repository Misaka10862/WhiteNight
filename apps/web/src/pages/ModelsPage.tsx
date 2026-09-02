import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchAvailableModels,
  fetchModelConfig,
  fetchSystemHealth,
  restartService,
  updateModelKeepAlive,
  updateModelProvider,
  updateTokenizerPath,
  type ModelProviderUpdate,
} from '../api'

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
  const [tokenizerPath, setTokenizerPath] = useState('')
  const [provider, setProvider] = useState<ModelProviderUpdate['provider']>('ollama')
  const [modelName, setModelName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [modelOptions, setModelOptions] = useState<string[]>([])
  const [restarting, setRestarting] = useState(false)

  useEffect(() => {
    if (modelConfig.data && !loaded) {
      setKeepAlive(modelConfig.data.ollama_keep_alive)
      setTokenizerPath(modelConfig.data.tokenizer_path ?? '')
      setProvider(modelConfig.data.provider)
      setModelName(modelConfig.data.model_name)
      setBaseUrl(modelConfig.data.base_url)
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
  const saveTokenizer = useMutation({
    mutationFn: updateTokenizerPath,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['model-config'] }),
  })
  const saveProvider = useMutation({
    mutationFn: updateModelProvider,
    onSuccess: () => {
      setApiKey('')
      setModelOptions([])
      queryClient.invalidateQueries({ queryKey: ['model-config'] })
      queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const fetchModels = useMutation({
    mutationFn: fetchAvailableModels,
    onSuccess: (result) => setModelOptions(result.models),
  })
  const restart = useMutation({
    mutationFn: async () => {
      const result = await restartService()
      const deadline = Date.now() + 10000
      while (Date.now() < deadline) {
        await new Promise((resolve) => window.setTimeout(resolve, 500))
        try {
          await fetchSystemHealth()
          return result
        } catch {
          // launchd is still replacing the process; keep polling until timeout.
        }
      }
      throw new Error('服务在 10 秒内未恢复')
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['system-health'] })
      setRestarting(false)
    },
    onMutate: () => setRestarting(true),
    onError: () => setRestarting(false),
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
        <h3>模型 Provider</h3>
        <div className="inline-form">
          <label>
            Provider
            <select value={provider} onChange={(event) => {
              setProvider(event.target.value as ModelProviderUpdate['provider'])
              setModelOptions([])
              fetchModels.reset()
            }}>
              <option value="ollama">本地 Ollama</option>
              <option value="openai">云端 OpenAI-compatible API</option>
            </select>
          </label>
          <label>
            模型名称
            <span className="model-picker">
              <input value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder={provider === 'ollama' ? 'qwen3:8b' : 'gpt-4o-mini'} />
              <button
                type="button"
                onClick={() => fetchModels.mutate({ provider, base_url: baseUrl, ...(provider === 'openai' && apiKey ? { api_key: apiKey } : {}) })}
                disabled={fetchModels.isPending || !baseUrl.trim()}
              >
                {fetchModels.isPending ? '获取中…' : '获取'}
              </button>
            </span>
            {modelOptions.length > 0 && (
              <select
                aria-label="可用模型列表"
                value={modelOptions.includes(modelName) ? modelName : ''}
                onChange={(event) => setModelName(event.target.value)}
              >
                <option value="">从列表选择…</option>
                {modelOptions.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            )}
          </label>
          <label>
            Base URL
            <input value={baseUrl} onChange={(event) => {
              setBaseUrl(event.target.value)
              setModelOptions([])
              fetchModels.reset()
            }} placeholder={provider === 'ollama' ? 'http://127.0.0.1:11434' : 'https://api.openai.com/v1'} />
          </label>
          {provider === 'openai' && (
            <label>
              API Key（仅写入 Keychain）
              <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={modelConfig.data?.api_key_configured ? '已配置，留空则保持不变' : '请输入 API Key'} autoComplete="new-password" />
            </label>
          )}
        </div>
        <p className="muted">
          当前：{modelConfig.data?.provider === 'openai' ? '云端 API' : '本地 Ollama'} · {modelConfig.data?.model_name ?? '未知'}
          {provider === 'openai' && ` · Keychain：${modelConfig.data?.api_key_configured ? '已配置' : '未配置'}`}
        </p>
        <div className="actions">
          <button
            onClick={() => saveProvider.mutate({ provider, model_name: modelName, base_url: baseUrl, ...(apiKey ? { api_key: apiKey } : {}) })}
            disabled={saveProvider.isPending || !modelName.trim() || !baseUrl.trim()}
          >
            {saveProvider.isPending ? '切换中…' : '保存并立即切换'}
          </button>
        </div>
        {saveProvider.isError && <div className="chat-error">Provider 保存失败：{String(saveProvider.error)}</div>}
        {saveProvider.isSuccess && <div className="chat-ok">Provider 已切换并持久化。</div>}
        {fetchModels.isError && <div className="chat-error">获取模型失败：{String(fetchModels.error)}</div>}
        {fetchModels.isSuccess && modelOptions.length === 0 && <p className="muted">Provider 未返回可用模型，请检查地址或服务端权限。</p>}
      </div>
      <div className="panel">
        <h3>服务管理</h3>
        <p className="muted">当前服务由 launchd 管理时，可以从这里重启 WhiteNight；手动启动时按钮会明确提示不支持。</p>
        <div className="actions">
          <button onClick={() => restart.mutate()} disabled={restart.isPending || restarting}>
            {restarting ? '服务重启中…' : restart.isPending ? '提交中…' : '重启 WhiteNight 服务'}
          </button>
        </div>
        {restart.isError && <div className="chat-error">重启失败：{String(restart.error)}</div>}
        {restarting && <div className="chat-ok">已请求 launchd 重启，正在等待服务恢复。</div>}
      </div>
      <div className="panel">
        <h3>上下文计数</h3>
        <div className="inline-form">
          <label>本地 tokenizer.json 路径<input value={tokenizerPath} onChange={(event) => setTokenizerPath(event.target.value)} placeholder="/absolute/path/tokenizer.json" /></label>
        </div>
        <div className="actions"><button disabled={!tokenizerPath || saveTokenizer.isPending} onClick={() => saveTokenizer.mutate(tokenizerPath)}>注册 tokenizer</button></div>
        <p className="muted">状态：{modelConfig.data?.tokenizer_available ? '精确计数可用' : '未配置，由模型处理上下文上限'} · 上限 {modelConfig.data?.context_tokens ?? '?'} tokens</p>
        {saveTokenizer.isError && <div className="chat-error">注册失败：{String(saveTokenizer.error)}</div>}
      </div>
      <div className="panel">
        <h3>QQ / OneBot</h3>
        <p className="muted">
          状态：{health.data?.onebot?.health?.logged_in ? '在线并已登录' : health.data?.onebot?.health?.reason === 'connection_refused' ? '离线（NapCat 未启动）' : '未确认'}
        </p>
        <p className="muted">
          原生表情：{health.data?.onebot?.stickers?.native_ready ?? 0} 张已绑定
          {health.data?.onebot?.stickers?.native_ready ? '' : '（需要填写 QQ/NapCat 表情 ID）'}
        </p>
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
