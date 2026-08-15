# WhiteNight 构建进度（过程性文档）

> 本文件随每次构建更新：记录已完成、未完成、问题与下一步。
> 构建大纲：`构建计划.md`。阶段结论与实测证据见 `docs/reports/`。

最后更新：2026-08-15（第 5 轮，阶段 4）

## 当前阶段

- **阶段 4 · 长期记忆**：核心已实现并通过测试，本轮收尾（报告 + 提交）。
- 下一阶段：**阶段 5 · 路由与 Agent 委派**。

## 已完成

### 阶段 0 · 工程初始化 ✅
- uv + Python 3.12、React/Vite/TS 前端、依赖锁、ruff/mypy/pytest、CI（无模型）
- 配置分层、Keychain、SQLCipher/Alembic、日志脱敏、ADR、契约文档、SOUL/AGENTS
- Git：`bcb46a2`、`4a365d5`；tag `phase-0`

### 阶段 1 · 高风险能力验证 ✅
- qwen3-vl:8b 文本 2.2s / 视觉内容 11.5s / 工具调用 Schema 通过；图片须挂 message
- Hermes Gateway 可启动；cua-driver 0.19.3 已安装（TCC 待用户授权）
- Codex MCP stdio 握手通过；SQLCipher/Keychain 原型通过
- Git：`4b0ee79`、`5656a07`；报告 `docs/reports/phase1-verification.md`

### 阶段 2 · 最小纵向链路 ✅
- 统一消息/会话 + 迁移 0002；ModelProvider/Ollama 流式；SOUL 上下文预算
- `/api/v1/chat/ws` 流式聊天 + 图片附件 + 会话持久化；WebUI 聊天/上传/恢复
- 实测重启恢复与 Vite 代理链路；ADR-0003、`docs/contracts/chat-ws.md`
- Git：`a302d0c`

### 阶段 3 · 工具、文件与文档 ✅
- PolicyEngine/一次性审批/会话授权/审计 + 迁移 0003；ToolExecutor 唯一入口
- 文件读写移动废纸篓删除、截图、搜索（DDG Lite + Bing 兜底）、页面提取
- 文本/代码、PDF（扫描页 OCR）、DOCX/XLSX/PPTX、图片 Apple Vision OCR、zip/tar 列表
- 70 个测试（含权限红队）；报告 `docs/reports/phase3-verification.md`
- Git：`1e5af82`

### 阶段 4 · 长期记忆 ✅（本轮）
- 三层模型：profile_facts / episodic_memories / session_summaries + 迁移 0004（FTS5 + 触发器）
- MemoryService：去重、冲突检测、编辑旧值立即失效、删除、导出 JSONL/Markdown
- 提取器：Ollama（严格 JSON）+ 规则回退 + 主回复后异步提取（不阻塞聊天）
- 混合召回：FTS5 词法 + 嵌入接口 + 时间衰减 + 访问加成；嵌入模型按需加载
- REST API：facts/episodes CRUD、冲突解决、retrieve、extract、export、summary
- 87 passed / 3 skipped；真实 Ollama 提取出 `居住地：杭州`、`喜好：雨天散步` 并可词法召回
- 报告：`docs/reports/phase4-verification.md`（随提交补齐）

## 未完成（按构建计划阶段）

| 阶段 | 内容 | 状态 |
|---|---|---|
| 5 | 结构化路由、Hermes/Codex Adapter、任务/进度/审批/中止事件、升级重试 | 待开始 |
| 6 | 完整 WebUI（记忆/任务/审批/权限/主动消息/模型/备份页面） | 记忆 API 已备好，页面待做 |
| 7 | launchd 后台服务、泊松主动消息调度 | 待开始 |
| 8 | QQ 私聊（NapCat + OneBot Adapter） | 待开始 |
| 9 | LoRA 人格固化 | 待开始 |
| 10 | 发布加固（72h、备份恢复演练、文档） | 待开始 |

阶段内已知缺口：
- 聊天模型 tool_calls 与 ToolExecutor 的接线（属阶段 5）
- 备份/恢复界面与加密备份实现（计划阶段 4 提及，核心放在阶段 10，界面在阶段 6）
- 旧版 .doc/.xls/.ppt 受控转换器（解析器已给出明确错误路径）
- 语义召回默认关闭：`embedding_model` 为空时只有 FTS5 词法，自然语言问句需要先配小型嵌入模型

## 问题记录（未解决）

1. **GitHub push 被拒**：OAuth 凭据缺 `workflow` scope，无法推送含 `.github/workflows/ci.yml`
   的提交。本地提交与 tag 完好。修复：`gh auth refresh -s workflow && git push -u origin main`。
2. **Hermes 任务级验证被阻塞**：Hermes 未登录任何模型 Provider（`hermes status` 全 ✗）。
   需用户执行 `hermes model` / `hermes auth` 登录后跑任务链路契约烟测。
3. **cua-driver TCC 待授权**：`hermes computer-use doctor` 显示辅助功能与屏幕录制未授予；
   需用户在系统设置授权或运行 `hermes computer-use permissions grant`。
4. **NapCat / QQ 未安装**：官方 npm 包已撤下，需用户下载构建并扫码登录 QQ 小号；
   OneBot Adapter 可先用 mock 开发。
5. **真实 file.delete / screen.capture 未做系统级烟测**：分别需要 Finder 自动化与屏幕录制
   权限；单元/集成测试已用受控 fake 覆盖状态机与审计。
6. **DuckDuckGo HTML 端点 202 反爬**：已用 DDG Lite + Bing 兜底解决并实测，但上游可能继续
   变化，升级需跑 `tests/test_web_tools.py` 与真实搜索烟测。
7. **OCR 可选依赖未进 check.sh**：`ocrmac` 依赖 pyobjc（macOS only），CI 不装；本地验证
   需 `uv sync --extra ocr`，否则 OCR 测试自动跳过。
8. **SQLite 时间戳 naive/aware 混用**：已用统一 naive-UTC 比较修复（审批/衰减），后续新增
   时间比较必须复用同一约定，防止 `TypeError`。

## 下一步（阶段 5 计划）

1. 路由：结构化 JSON 输出（类别/执行者/风险）+ 规则覆盖 + 用户指定 + 升级策略。
2. Codex MCP Adapter：stdio 会话、线程续接、工作目录、超时与错误恢复（已有握手证据）。
3. Hermes Gateway Adapter：HTTP/WS 任务、进度、审批与中止（等用户登录后做真实契约测试）。
4. 统一任务事件与 ChatService 接线：模型 tool_calls → ToolExecutor（审批事件给 WebUI）。
5. 黄金路由集 `evals/routing/` 与路由测试。

## 验证命令

```bash
./scripts/check.sh                        # ruff + pytest + 前端 lint/build
uv run mypy src/whitenight                 # 严格类型检查
WHITENIGHT_TEST_OLLAMA=1 uv run pytest tests/test_ollama_provider.py -q
uv run alembic upgrade head                # 数据库迁移
uv run scripts/verify_phase1.py --smoke-model --smoke-gateway
```
