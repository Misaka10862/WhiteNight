import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  archiveCharacter,
  createLorebook,
  exportCharacter,
  fetchCharacterRevisions,
  fetchCharacters,
  fetchLorebooks,
  fetchPersona,
  fetchPromptPreview,
  fetchPromptProfile,
  importCharacter,
  restoreCharacterRevision,
  updateCharacter,
  updateLorebook,
  updatePersona,
  updatePromptProfile,
  type CharacterCard,
  type CharacterRecord,
  type LorebookData,
  type PromptBlock,
} from '../api'
import { downloadBlob, readCharacterPng, writeCharacterPng } from '../characterCardPng'

type View = 'profile' | 'prompt' | 'lorebook' | 'inspect'

const EMPTY_CARD: CharacterCard = {
  spec: 'chara_card_v3',
  spec_version: '3.0',
  data: {
    name: '新角色', description: '', personality: '', scenario: '', first_mes: '', mes_example: '',
    creator_notes: '', system_prompt: '', post_history_instructions: '', alternate_greetings: [],
    tags: [], creator: 'WhiteNight', character_version: '1', extensions: {},
  },
}

const EMPTY_LOREBOOK: LorebookData = {
  name: '新世界书', entries: [], scan_depth: 2, token_budget: 2048, recursive: false,
  max_recursion_steps: 8, min_activations: 0, extensions: {},
}

export default function CharactersPage({ sessionId }: { sessionId: string | null }) {
  const queryClient = useQueryClient()
  const characters = useQuery({ queryKey: ['characters'], queryFn: fetchCharacters })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [view, setView] = useState<View>('profile')
  const [error, setError] = useState<string | null>(null)
  const importInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!selectedId && characters.data?.length) setSelectedId(characters.data[0].id)
  }, [characters.data, selectedId])
  const selected = characters.data?.find((item) => item.id === selectedId) ?? null

  const createBlank = useMutation({
    mutationFn: () => importCharacter(structuredClone(EMPTY_CARD)),
    onSuccess: (record) => {
      queryClient.invalidateQueries({ queryKey: ['characters'] })
      setSelectedId(record.id)
    },
    onError: (reason) => setError(String(reason)),
  })

  const importFile = async (file?: File) => {
    if (!file) return
    try {
      const card = file.type === 'image/png'
        ? await readCharacterPng(file)
        : JSON.parse(await file.text()) as CharacterCard
      const avatar = file.type === 'image/png' ? await fileToDataUrl(file) : null
      const record = await importCharacter(card, avatar)
      await queryClient.invalidateQueries({ queryKey: ['characters'] })
      setSelectedId(record.id)
      setError(null)
    } catch (reason) {
      setError(String(reason))
    }
  }

  return (
    <section className="page character-workspace" aria-label="角色与编排">
      <div className="page-heading">
        <div>
          <h2>角色与编排</h2>
          <p className="hint">当前会话绑定的角色不会被直接替换。</p>
        </div>
        <div className="actions compact-actions">
          <button onClick={() => createBlank.mutate()}>新建角色</button>
          <button onClick={() => importInput.current?.click()}>导入卡片</button>
          <input ref={importInput} hidden type="file" accept=".json,image/png" onChange={(event) => importFile(event.target.files?.[0])} />
        </div>
      </div>
      {error && <div className="chat-error" role="alert">{error}</div>}
      <div className="character-layout">
        <aside className="character-list" aria-label="角色库">
          {(characters.data ?? []).map((character) => (
            <button key={character.id} className={selectedId === character.id ? 'character-row active' : 'character-row'} onClick={() => setSelectedId(character.id)}>
              <span className="avatar-placeholder">{character.name.slice(0, 1)}</span>
              <span><strong>{character.name}</strong><small>v{character.revision}{character.is_default ? ' · 默认' : ''}</small></span>
            </button>
          ))}
        </aside>
        <div className="character-editor">
          {!selected && <div className="empty-state">尚无角色</div>}
          {selected && (
            <>
              <div className="tabs compact-tabs">
                {([['profile', '档案'], ['prompt', 'Prompt'], ['lorebook', '世界书'], ['inspect', '检查器']] as const).map(([id, label]) => (
                  <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>{label}</button>
                ))}
              </div>
              {view === 'profile' && <ProfileEditor character={selected} onError={setError} />}
              {view === 'prompt' && <PromptEditor characterId={selected.id} onError={setError} />}
              {view === 'lorebook' && <LorebookEditor characterId={selected.id} onError={setError} />}
              {view === 'inspect' && <PromptInspector sessionId={sessionId} />}
            </>
          )}
        </div>
      </div>
    </section>
  )
}

function ProfileEditor({ character, onError }: { character: CharacterRecord; onError: (value: string | null) => void }) {
  const queryClient = useQueryClient()
  const [card, setCard] = useState<CharacterCard>(structuredClone(character.card))
  const persona = useQuery({ queryKey: ['persona'], queryFn: fetchPersona })
  const revisions = useQuery({ queryKey: ['character-revisions', character.id], queryFn: () => fetchCharacterRevisions(character.id) })
  const [personaName, setPersonaName] = useState('主人')
  const [personaDescription, setPersonaDescription] = useState('')
  useEffect(() => setCard(structuredClone(character.card)), [character])
  useEffect(() => {
    if (persona.data) {
      setPersonaName(persona.data.name)
      setPersonaDescription(persona.data.description)
    }
  }, [persona.data])
  const save = useMutation({
    mutationFn: () => updateCharacter(character.id, card),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['characters'] }),
    onError: (reason) => onError(String(reason)),
  })
  const savePersona = useMutation({
    mutationFn: () => updatePersona(personaName, personaDescription),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['persona'] }),
  })
  const setField = (name: keyof CharacterCard['data'], value: unknown) =>
    setCard((current) => ({ ...current, data: { ...current.data, [name]: value } }))

  const exportCard = async (format: 'json' | 'png') => {
    try {
      const data = await exportCharacter(character.id)
      if (format === 'json') {
        downloadBlob(new Blob([JSON.stringify(data.card, null, 2)], { type: 'application/json' }), `${character.name}.json`)
      } else if (data.avatar_data_url) {
        downloadBlob(await writeCharacterPng(data.avatar_data_url, data.card), `${character.name}.png`)
      } else {
        throw new Error('该角色没有 PNG 头像，无法导出 PNG 卡片')
      }
    } catch (reason) { onError(String(reason)) }
  }

  return (
    <div className="editor-stack">
      <div className="form-grid">
        <label>名称<input value={card.data.name} onChange={(event) => setField('name', event.target.value)} /></label>
        <label>版本<input value={card.data.character_version} onChange={(event) => setField('character_version', event.target.value)} /></label>
      </div>
      <TextField label="描述" value={card.data.description} onChange={(value) => setField('description', value)} />
      <TextField label="性格" value={card.data.personality} onChange={(value) => setField('personality', value)} />
      <TextField label="场景" value={card.data.scenario} onChange={(value) => setField('scenario', value)} />
      <TextField label="System Prompt" value={card.data.system_prompt} onChange={(value) => setField('system_prompt', value)} large />
      <TextField label="Post-History" value={card.data.post_history_instructions} onChange={(value) => setField('post_history_instructions', value)} />
      <TextField label="首句" value={card.data.first_mes} onChange={(value) => setField('first_mes', value)} />
      <TextField label="备选开场（每行一条）" value={card.data.alternate_greetings.join('\n')} onChange={(value) => setField('alternate_greetings', value.split('\n').filter(Boolean))} />
      <TextField label="示例对话" value={card.data.mes_example} onChange={(value) => setField('mes_example', value)} large />
      <div className="actions">
        <button onClick={() => save.mutate()} disabled={save.isPending}>保存修订</button>
        <button onClick={() => exportCard('json')}>导出 JSON</button>
        <button onClick={() => exportCard('png')}>导出 PNG</button>
        {!character.is_default && <button className="danger" onClick={async () => { await archiveCharacter(character.id); queryClient.invalidateQueries({ queryKey: ['characters'] }) }}>归档</button>}
      </div>
      <details>
        <summary>修订历史</summary>
        <div className="revision-list">
          {(revisions.data ?? []).map((revision) => <button key={revision.id} onClick={async () => { await restoreCharacterRevision(character.id, revision.id); queryClient.invalidateQueries({ queryKey: ['characters'] }) }}>v{revision.revision} · {revision.created_at.slice(0, 16).replace('T', ' ')}</button>)}
        </div>
      </details>
      <div className="section-divider" />
      <h3>用户 Persona</h3>
      <div className="form-grid"><label>称呼<input value={personaName} onChange={(event) => setPersonaName(event.target.value)} /></label></div>
      <TextField label="身份描述" value={personaDescription} onChange={setPersonaDescription} />
      <div className="actions"><button onClick={() => savePersona.mutate()}>保存 Persona</button></div>
    </div>
  )
}

function PromptEditor({ characterId, onError }: { characterId: string; onError: (value: string | null) => void }) {
  const queryClient = useQueryClient()
  const profile = useQuery({ queryKey: ['prompt-profile', characterId], queryFn: () => fetchPromptProfile(characterId) })
  const [blocks, setBlocks] = useState<PromptBlock[]>([])
  useEffect(() => setBlocks(profile.data?.blocks ?? []), [profile.data])
  const save = useMutation({
    mutationFn: () => updatePromptProfile(characterId, blocks.map((block, order) => ({ ...block, order: order * 10 + 100 }))),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['prompt-profile', characterId] }),
    onError: (reason) => onError(String(reason)),
  })
  const update = (index: number, patch: Partial<PromptBlock>) => setBlocks((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item))
  return (
    <div className="editor-stack">
      <div className="prompt-pinned"><strong>固定</strong><span>安全内核</span><span>Main Prompt</span><span>可信运行时约束</span></div>
      {blocks.map((block, index) => (
        <div className="prompt-block" key={block.id}>
          <div className="prompt-block-head">
            <input value={block.name} onChange={(event) => update(index, { name: event.target.value })} />
            <select value={block.role} onChange={(event) => update(index, { role: event.target.value as PromptBlock['role'] })}><option>system</option><option>user</option><option>assistant</option></select>
            <select value={block.position} onChange={(event) => update(index, { position: event.target.value as PromptBlock['position'] })}><option value="relative">相对</option><option value="in_chat">聊天深度</option></select>
            <input className="number-input" type="number" value={block.depth} onChange={(event) => update(index, { depth: Number(event.target.value) })} aria-label="深度" />
            <button title="上移" disabled={index === 0} onClick={() => setBlocks((items) => swap(items, index, index - 1))}>↑</button>
            <button title="下移" disabled={index === blocks.length - 1} onClick={() => setBlocks((items) => swap(items, index, index + 1))}>↓</button>
            <button title="移除" onClick={() => setBlocks((items) => items.filter((_, itemIndex) => itemIndex !== index))}>×</button>
          </div>
          <textarea value={block.content} onChange={(event) => update(index, { content: event.target.value })} />
        </div>
      ))}
      <div className="actions">
        <button onClick={() => setBlocks((items) => [...items, { id: crypto.randomUUID(), name: '自定义 Prompt', role: 'system', content: '', enabled: true, position: 'relative', depth: 0, order: 100, triggers: [], outlet: null }])}>添加模块</button>
        <button onClick={() => save.mutate()} disabled={save.isPending}>保存编排</button>
      </div>
    </div>
  )
}

function LorebookEditor({ characterId, onError }: { characterId: string; onError: (value: string | null) => void }) {
  const queryClient = useQueryClient()
  const lorebooks = useQuery({ queryKey: ['lorebooks'], queryFn: fetchLorebooks })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = lorebooks.data?.find((item) => item.id === selectedId) ?? null
  const [draft, setDraft] = useState('')
  useEffect(() => { if (selected) setDraft(JSON.stringify(selected.data, null, 2)) }, [selected])
  const create = async () => {
    try {
      const result = await createLorebook(EMPTY_LOREBOOK, characterId)
      await queryClient.invalidateQueries({ queryKey: ['lorebooks'] })
      setSelectedId(result.id)
    } catch (reason) { onError(String(reason)) }
  }
  const save = async () => {
    if (!selected) return
    try {
      await updateLorebook(selected.id, JSON.parse(draft) as LorebookData)
      await queryClient.invalidateQueries({ queryKey: ['lorebooks'] })
    } catch (reason) { onError(String(reason)) }
  }
  return (
    <div className="editor-stack">
      <div className="toolbar-row"><select value={selectedId ?? ''} onChange={(event) => setSelectedId(event.target.value || null)}><option value="">选择世界书</option>{(lorebooks.data ?? []).map((item) => <option key={item.id} value={item.id}>{item.data.name} · v{item.revision}</option>)}</select><button onClick={create}>新建并绑定</button></div>
      {selected && <><textarea className="json-editor" value={draft} onChange={(event) => setDraft(event.target.value)} spellCheck={false} /><div className="actions"><button onClick={save}>校验并保存</button></div></>}
      {!selected && <div className="empty-state">选择或新建世界书</div>}
    </div>
  )
}

function PromptInspector({ sessionId }: { sessionId: string | null }) {
  const preview = useQuery({ queryKey: ['prompt-preview', sessionId], queryFn: () => fetchPromptPreview(sessionId!), enabled: Boolean(sessionId) })
  if (!sessionId) return <div className="empty-state">先选择一个会话</div>
  return <div className="editor-stack"><div className="inspector-status"><strong>{preview.data?.tokenizer === 'exact' ? `${preview.data.total_tokens} tokens` : 'Token 计数不可用'}</strong><button onClick={() => preview.refetch()}>刷新</button></div><div className="manifest-list">{(preview.data?.manifest ?? []).map((item) => <div key={`${item.source}-${item.id}`}><span>{item.name}</span><code>{item.role} · {item.source} · {item.token_count ?? '?'}</code></div>)}</div><details><summary>最终 messages</summary><pre className="pre inspector-pre">{JSON.stringify(preview.data?.messages ?? [], null, 2)}</pre></details><details><summary>世界书激活</summary><pre className="pre">{JSON.stringify(preview.data?.activated_lore ?? [], null, 2)}</pre></details></div>
}

function TextField({ label, value, onChange, large = false }: { label: string; value: string; onChange: (value: string) => void; large?: boolean }) {
  return <label className="stacked-field">{label}<textarea className={large ? 'large' : ''} value={value} onChange={(event) => onChange(event.target.value)} /></label>
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function swap<T>(items: T[], left: number, right: number): T[] {
  const result = [...items]
  ;[result[left], result[right]] = [result[right], result[left]]
  return result
}
