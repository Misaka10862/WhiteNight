# 阶段 6 完整 WebUI 实测报告（2026-08-15）

> 复跑：`./scripts/check.sh`（ALL CHECKS PASSED）；`uv run pytest`（102 passed, 4 skipped）

## 1. 工作台页面

| 页面 | 能力 |
|---|---|
| 聊天 | 会话列表、流式回复、图片上传、委派任务事件气泡 |
| 会话 | 重命名、导出 Markdown/JSONL、删除（立即移除 + 无正文审计） |
| 记忆 | 混合检索、事实增改删、冲突保留/放弃、情景记忆增删、导出 |
| 任务 | 执行者/状态/风险/尝试次数/thread/产物/错误 + 中止 |
| 审批 | 风险/范围/参数摘要 + 允许一次/允许本次会话/拒绝 |
| 权限 | 工具风险规则表 + 会话授权撤销 |
| 模型 | 数据库/模型/Hermes/Codex 健康状态 |
| 约束 | SOUL.md / AGENTS.md 查看与编辑 |
| 主动/日志/备份 | 诚实占位，能力在阶段 7/10 接入，不做假开关 |

## 2. 配套后端 API（阶段 6 新增）

- `PATCH/DELETE /api/v1/sessions/{id}`、`GET .../export?fmt=`
- `GET /api/v1/approvals/pending`、`POST .../{code}/approve|reject`
- `GET /api/v1/policy/rules`、`GET/DELETE /api/v1/policy/grants[/{id}]`
- `GET /api/v1/system/health`（DB + 模型 + Codex/Hermes 健康）
- `GET/PUT /api/v1/rules/{SOUL|AGENTS}`

## 3. 可用性与无障碍

- 窄窗口：导航折叠为汉堡按钮，会话列/分栏变单列（CSS @media）。
- 键盘：聊天 Enter 发送、Shift+Enter 换行；表单原生提交。
- aria-label 覆盖主导航、聊天输入、图片选择、各页面 section；
  任务/审批状态用文本标记，错误用 role="alert"。

## 4. 实测

- 前端：eslint ✓、tsc ✓、vite build ✓（85 modules）。
- Vite 代理全链路：创建/重命名/导出/删除会话、事实增删与检索、
  任务/审批/权限/模型/规则读取，全部通过。
- 真实 Ollama 流式聊天经 Vite WebSocket 代理：`只回复两个字：在的` → 「在的」。
- 后端 102 tests：含会话删除审计、审批不可重放、会话授权撤销、
  规则文件安全读写、系统健康。

## 5. 边界

- 真实浏览器视觉回归需用户人工确认（tsc/build/API 已覆盖）。
- 主动消息、日志与备份页面为占位；对应后端按阶段 7/10 交付。
