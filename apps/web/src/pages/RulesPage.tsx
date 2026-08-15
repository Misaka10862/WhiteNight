import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchRuleFile, saveRuleFile } from '../api'

export default function RulesPage() {
  const queryClient = useQueryClient()
  const [active, setActive] = useState<'SOUL' | 'AGENTS'>('SOUL')
  const file = useQuery({ queryKey: ['rule-file', active], queryFn: () => fetchRuleFile(active) })
  const [draft, setDraft] = useState('')
  const [loadedKey, setLoadedKey] = useState<string | null>(null)
  useEffect(() => {
    if (file.data !== undefined && loadedKey !== active) {
      setDraft(file.data)
      setLoadedKey(active)
    }
  }, [file.data, active, loadedKey])
  const save = useMutation({
    mutationFn: (content: string) => saveRuleFile(active, content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rule-file', active] })
      alert('已保存')
    },
  })

  return (
    <section className="page" aria-label="临时约束">
      <h2>临时约束文件</h2>
      <p className="hint">
        SOUL.md 承载初期人格；AGENTS.md 是工程规则。两者可查看可编辑，安全与权限约束不能被聊天内容修改。
      </p>
      <div className="tabs">
        {(['SOUL', 'AGENTS'] as const).map((name) => (
          <button key={name} className={active === name ? 'active' : ''} onClick={() => setActive(name)}>
            {name}
          </button>
        ))}
      </div>
      <textarea
        className="rule-editor"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        aria-label={`${active} 内容`}
        spellCheck={false}
      />
      <div className="actions">
        <button onClick={() => save.mutate(draft)} disabled={save.isPending}>
          保存
        </button>
      </div>
    </section>
  )
}
