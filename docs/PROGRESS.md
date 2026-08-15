# WhiteNight 构建进度（过程性文档）

> 本文件随每次构建更新：记录已完成、未完成、问题与下一步。
> 构建大纲：`构建计划.md`。阶段结论与实测证据见 `docs/reports/`。

最后更新：2026-08-15（第 8 轮，阶段 7）

## 当前阶段

- **阶段 7 · 后台服务与主动行为**：核心已实现并实测，本轮收尾。
- 下一阶段：**阶段 8 · QQ 私聊**。

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
- 报告：`docs/reports/phase4-verification.md`

### 阶段 5 · 路由与 Agent 委派 ✅（本轮）
- 路由：规则优先（用户指定/图片/代码/GUI/记忆/搜索/文件）+ 可选 LLM 结构化输出 + 本地兜底
- 黄金路由集 `evals/routing/golden.jsonl`（16 例），目标准确率 ≥ 0.9 实测通过
- 统一委派事件（started/progress/result/error/aborted）+ DelegateProvider 协议
- Codex MCP Adapter：stdio JSON-RPC、initialize/tools、codex/codex-reply 线程续接、
  沙箱 workspace-write、审批策略 on-request；真实握手测试通过
- Hermes Gateway Adapter：健康/认证契约；submit 在用户登录 Provider 前安全快速失败
- DelegateManager：任务持久化（迁移 0005）、有限重试、中止、不可用快速失败；
  ChatService 集成后委派失败不破坏主会话（实测可继续本地聊天）
- 任务 API：/api/v1/tasks 列表/详情/中止
- 97 passed / 4 skipped
- 报告：`docs/reports/phase5-verification.md`（随提交补齐）

### 阶段 6 · 完整 WebUI ✅（本轮）
- 工作台导航：聊天/会话/记忆/任务/审批/权限/模型/约束/主动/日志/备份
- 聊天页：会话列表、流式气泡、图片、委派任务事件气泡；会话页：重命名/导出/删除
- 记忆页：检索、事实增改删、冲突保留/放弃、情景记忆、JSONL/Markdown 导出
- 任务页：执行者/状态/风险/产物/错误/中止；审批页：风险/参数摘要/允许/拒绝
- 权限页：工具风险规则 + 会话授权撤销；模型页：DB/模型/Hermes/Codex 健康
- 约束页：SOUL.md / AGENTS.md 查看编辑（服务端安全写入）
- 主动消息/日志/备份页面：诚实占位（能力分别在阶段 7/10 接入，不做假开关）
- 后端配套 API：会话 rename/delete/export、approvals approve/reject、policy rules/grants、
  system health、rules 读写；102 passed / 4 skipped
- 窄窗口响应式布局 + 键盘 Enter 发送 + 导航/aria 标签
- 实测：Vite 代理下会话/记忆/任务/审批/权限/模型/规则全链路 + 真实 Ollama 流式聊天通过
- 报告：`docs/reports/phase6-verification.md`

### 阶段 7 · 后台服务与主动行为 ✅（本轮）
- 迁移 0006 proactive_state：频率/静默/暂停/最近活动/最近发送/下次候选持久化
- 泊松调度：指数间隔 + 静默时段 + 最近活动抑制 + 过期不补发（睡眠/断网安全）
- ProactiveService：候选生成、消息组合（人格 + 长期记忆）、有限重试、日志发送器
- 后台循环随 API 生命周期运行（30s tick），WebUI 关闭不影响服务
- 聊天用户消息自动记录最近活动；主动消息 API：status/config/pause/resume
- WebUI 主动消息页从占位升级为真实配置页
- launchd：plist 模板 + install/check 脚本；菜单栏状态入口 Swift 源码已编译验证
- 110 passed / 4 skipped；真实服务 API 实测通过
- 报告：`docs/reports/phase7-verification.md`（随提交补齐）

## 未完成（按构建计划阶段）

| 阶段 | 内容 | 状态 |
|---|---|---|
| 5 | 结构化路由、Hermes/Codex Adapter、任务/进度/审批/中止事件、升级重试 | ✅ 核心完成 |
| 6 | 完整 WebUI（记忆/任务/审批/权限/模型/规则页面） | ✅ 核心完成（主动/日志/备份为诚实占位） |
| 7 | launchd 后台服务、泊松主动消息调度 | ✅ 核心完成（真实发送器 QQ 在阶段 8） |
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
9. **Hermes submit 契约未锁定**：Gateway 认证通过但未登录 Provider；Adapter 在未登录时
   快速失败（已实测 `DelegateUnavailableError`）。用户登录后需完成真实任务链路契约测试，
   再固化 submit 端点 payload。
10. **Codex 真实任务未运行**：MCP 握手/工具列表实测通过；为避免消耗云端配额，编码任务
    以 Fake Provider 做状态机测试。真实短任务烟测（如生成一个 hello.py）留待用户确认后执行。
11. **WebUI 未做真实浏览器视觉回归**：已通过 tsc/eslint/build、Vite 代理全链路与 API 工作流
    验证；窄窗口/键盘/无障碍需要用户在本机打开 `npm run dev` 做一次人工确认。

## 下一步（阶段 8 计划）

1. OneBot 11 Adapter：事件幂等去重、顺序处理、断线重连、限频、消息分片。
2. 所有者白名单：只有配置的 QQ 号能触发工具和处理审批。
3. 支持私聊文字/图片/文件/引用；任务进度与 QQ 内审批。
4. NapCat 安装与 QQ 小号登录需用户操作；开发用 mock OneBot 服务器先行。

## 验证命令

```bash
./scripts/check.sh                        # ruff + pytest + 前端 lint/build
uv run mypy src/whitenight                 # 严格类型检查
WHITENIGHT_TEST_OLLAMA=1 uv run pytest tests/test_ollama_provider.py -q
uv run alembic upgrade head                # 数据库迁移
uv run scripts/verify_phase1.py --smoke-model --smoke-gateway
```
