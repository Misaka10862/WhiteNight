# 阶段 5 路由与 Agent 委派 实测报告（2026-08-15）

> 复跑：`uv run pytest`（97 passed, 4 skipped）
> 阶段 5 退出条件：黄金路由集达到目标准确率；Hermes/Codex 故障不破坏主会话且可安全重试。

## 1. 路由

- `RuleRouter`：规则优先、高精度。顺序：用户指定 → 图片问答 → 编码规则 →
  GUI/跨应用 → 记忆 → 搜索 → 文件操作 → 默认本地陪伴。
- `RoutingEngine`：规则 → 可选 `OllamaRoutingRouter`（严格 JSON）→ 本地兜底；
  显式 `user_override` 在权限允许范围内服从。
- 黄金集 `evals/routing/golden.jsonl`（16 例）：
  companionship/image_qa/memory/search/file_op/gui/code/user-override 全覆盖，
  **准确率 ≥ 0.9 达标**（测试断言）。

## 2. 委派协议与适配器

- `DelegateEvent` 标准信封：queued/started/progress/approval_required/artifact/
  result/error/aborted；`DelegateProvider` 协议统一 Hermes 与 Codex。
- **Codex MCP Adapter（实测通过）**：
  - stdio JSON-RPC 客户端（initialize → tools/list → tools/call）；
  - `codex`（新会话，cwd/sandbox=workspace-write/approval-policy=on-request）
    与 `codex-reply`（threadId 续接）；
  - 真实握手测试 `WHITENIGHT_TEST_CODEX_MCP=1` → 2 passed，工具列表为
    `codex` + `codex-reply`；
  - 超时/进程退出转为 `DelegateError`，可安全重试。
- **Hermes Gateway Adapter（实测通过）**：
  - `/api/status` 健康检查成功（v0.17.0）；
  - `/api/auth/me` 401/403 → `DelegateUnavailableError`（实测触发），
    submit 契约在用户登录 Provider 后锁定，避免猜测协议产生副作用。

## 3. 任务管理

- 迁移 `0005 agent_tasks`：执行者/类别/状态/风险/thread_id/产物/错误/尝试次数。
- `DelegateManager`：运行/重试（失败有限重试并产生 progress 事件）/中止/
  不可用快速失败；终态持久化。
- 任务 API：`GET /api/v1/tasks`、`GET /api/v1/tasks/{id}`、
  `POST /api/v1/tasks/{id}/abort`。
- ChatService 集成：路由到 Codex/Hermes 时透传 `type:"task"` 事件；
  结果原文落库并加一行人格化说明（技术内容不修改）；
  **委派失败后同会话普通聊天继续可用（集成测试）**。

## 4. 故障与恢复验证

- Fake Codex 成功：任务 `succeeded` 且 thread_id 持久化。
- Flaky Provider：第 1 次失败 → 第 2 次成功，`attempts=2`。
- Unavailable：快速失败为 error 事件，主会话仍能本地聊天。
- 中止：任务状态 → `aborted`。

## 5. 边界（记录在 PROGRESS）

- Hermes submit 端点契约需用户登录 Provider 后做实任务测试。
- Codex 真实编码任务未运行（避免消耗配额），MCP 握手已实测。
- 进度事件：Codex MCP 单次调用不提供流式部分内容，当前只有 started/result；
  Hermes 契约锁定后应提供真实进度。不伪造未发生的步骤。
