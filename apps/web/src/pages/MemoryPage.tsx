import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createEpisode,
  createFact,
  deleteEpisode,
  deleteFact,
  exportMemory,
  fetchEpisodes,
  fetchFacts,
  resolveFact,
  retrieveMemory,
  updateFact,
  type MemoryHit,
} from '../api'

export default function MemoryPage() {
  const queryClient = useQueryClient()
  const facts = useQuery({ queryKey: ['facts'], queryFn: fetchFacts })
  const episodes = useQuery({ queryKey: ['episodes'], queryFn: fetchEpisodes })
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<MemoryHit[]>([])
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')
  const [newEpisode, setNewEpisode] = useState('')
  const [error, setError] = useState<string | null>(null)

  const addFact = useMutation({
    mutationFn: () => createFact({ key: newKey, value: newValue }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['facts'] })
      setNewKey('')
      setNewValue('')
    },
    onError: (err) => setError(String(err)),
  })
  const editFact = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string }) => updateFact(id, value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['facts'] }),
  })
  const removeFact = useMutation({
    mutationFn: deleteFact,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['facts'] }),
  })
  const resolve = useMutation({
    mutationFn: ({ id, keep }: { id: string; keep: boolean }) => resolveFact(id, keep),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['facts'] }),
  })
  const addEpisode = useMutation({
    mutationFn: () => createEpisode({ content: newEpisode }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['episodes'] })
      setNewEpisode('')
    },
  })
  const removeEpisode = useMutation({
    mutationFn: deleteEpisode,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['episodes'] }),
  })

  return (
    <section className="page" aria-label="长期记忆">
      <h2>长期记忆</h2>
      {error && (
        <div className="chat-error" role="alert">
          {error}
        </div>
      )}

      <div className="split">
        <div className="panel">
          <h3>检索</h3>
          <form
            className="inline-form"
            onSubmit={async (event) => {
              event.preventDefault()
              if (!query.trim()) return
              setHits(await retrieveMemory(query))
            }}
          >
            <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="记忆检索" />
            <button type="submit">检索</button>
          </form>
          <ul className="card-list">
            {hits.map((hit) => (
              <li key={`${hit.item_type}-${hit.item_id}`} className="card">
                <strong>[{hit.item_type}]</strong> {hit.content}
                <span className="muted">score={hit.score.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="panel">
          <h3>结构化档案</h3>
          <form
            className="inline-form"
            onSubmit={(event) => {
              event.preventDefault()
              if (newKey.trim() && newValue.trim()) addFact.mutate()
            }}
          >
            <input value={newKey} onChange={(event) => setNewKey(event.target.value)} placeholder="key（如 喜好）" />
            <input value={newValue} onChange={(event) => setNewValue(event.target.value)} placeholder="value" />
            <button type="submit">新增</button>
          </form>
          <ul className="card-list">
            {(facts.data ?? []).map((fact) => (
              <li key={fact.id} className="card">
                <strong>{fact.key}</strong>：{fact.value}
                {fact.conflict_state === 'conflicted' && <span className="warn"> 冲突</span>}
                <span className="muted"> 置信 {fact.confidence.toFixed(2)}</span>
                <div className="actions">
                  <button
                    onClick={() => {
                      const value = window.prompt('新值', fact.value)
                      if (value) editFact.mutate({ id: fact.id, value })
                    }}
                  >
                    编辑
                  </button>
                  {fact.conflict_state === 'conflicted' && (
                    <button onClick={() => resolve.mutate({ id: fact.id, keep: true })}>保留此值</button>
                  )}
                  {fact.conflict_state === 'conflicted' && (
                    <button onClick={() => resolve.mutate({ id: fact.id, keep: false })}>放弃此值</button>
                  )}
                  <button className="danger" onClick={() => removeFact.mutate(fact.id)}>
                    删除
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="panel">
        <h3>情景记忆</h3>
        <form
          className="inline-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (newEpisode.trim()) addEpisode.mutate()
          }}
        >
          <input value={newEpisode} onChange={(event) => setNewEpisode(event.target.value)} placeholder="重要事件、承诺、共同经历…" />
          <button type="submit">新增</button>
        </form>
        <ul className="card-list">
          {(episodes.data ?? []).map((episode) => (
            <li key={episode.id} className="card">
              {episode.content}
              <span className="muted"> 重要 {episode.importance.toFixed(2)}</span>
              <div className="actions">
                <button className="danger" onClick={() => removeEpisode.mutate(episode.id)}>
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="actions">
        <button onClick={() => exportMemory('markdown')}>导出 Markdown</button>
        <button onClick={() => exportMemory('jsonl')}>导出 JSONL</button>
      </div>
    </section>
  )
}
