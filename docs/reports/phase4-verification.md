# 阶段 4 长期记忆 实测报告（2026-08-15）

> 复跑：`uv run pytest`（87 passed, 3 skipped，其中 Ollama/OCR 为可选集成测试）

## 1. 数据模型（迁移 0004）

- `profile_facts`：结构化档案；key/value、置信度、来源消息、状态
  （active/superseded/deleted）、冲突状态（none/conflicted/resolved）。
- `episodic_memories`：情景记忆；内容、来源、置信度、重要性、访问计数、
  软删除时间。
- `session_summaries`：滚动摘要（每会话保留最新）。
- FTS5：`profile_facts_fts` 与 `episodic_memories_fts`（unicode61），
  由 SQLite 触发器随增删改同步；触发器用普通 `DELETE ... WHERE rowid`
  而非 FTS5 特殊命令（Python 3.12/3.14 SQLite 对 `'delete'` 特殊插入
  返回 SQL logic error，实测后改用 DELETE 语法）。

## 2. 语义约束（红队已验证）

- 同 key 同 value 自动去重并取最高置信度。
- 同 key 不同 value → 双方标记 `conflicted`；重复确认某值自动解决。
- 编辑事实 → 旧值立即 `superseded`，`list_facts`/检索只返回新值。
- 删除 → 默认列表与 FTS 检索立即不可见，并写不含正文的审计事件。
- 用户手工 `resolve` 冲突：保留项生效，其余全部失效。

## 3. 提取与召回

- `RuleBasedMemoryExtractor`（确定性回退）与 `OllamaMemoryExtractor`
  （严格 JSON Schema，解析失败返回空，不阻塞聊天）。
- 主回复后 `asyncio.create_task` 异步提取；任务引用由 ChatService 持有防 GC。
- 召回：FTS5 词法（rank + LIKE 兜底）权重 0.6 + 语义余弦 0.4；
  情景记忆带 30 天半衰期时间衰减与访问计数加成；检索命中自动 touch。
- `embedding_model` 为空时语义层降级为 null（词法仍工作）；
  自然语言问句需配置小型嵌入模型（按需加载）。

## 4. API

`/api/v1/memory/facts` CRUD + resolve；`/api/v1/memory/episodes` CRUD；
`/api/v1/memory/extract`、`/retrieve`、`/export?fmt=jsonl|markdown`；
`/api/v1/sessions/{id}/summary` 与 `/summarize`。

## 5. 实测

- 真实 Ollama（qwen3-vl:8b）从「我住在杭州，最喜欢雨天散步」提取：
  `居住地：杭州`、`喜好：雨天散步`、`称呼：主人` + 1 条情景记忆。
- 词法召回：查询「杭州」→ `居住地：杭州`；「雨天」→ 情景记忆。
- 导出：JSONL 含 type/id/source/created_at；Markdown 分档案与情景记忆两节。

## 6. 边界

- 语义召回未启用嵌入模型（配置为空），跨天自然语言问句需先安装/配置嵌入模型。
- 备份/恢复界面与加密备份实现按计划在阶段 6/10 完成；导出已在阶段 4 提供。
- 删除审计不含正文（符合构建计划 10.2）。
