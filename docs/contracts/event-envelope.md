# 标准化事件信封（v0.1 草案）

所有渠道、任务执行器和后台调度器统一发布本信封。阶段 2 起由 `api` 包按此结构实现，
WebUI 与 OneBot 适配器只依赖信封字段，不解析任何执行器的原始终端文本。

```json
{
  "envelope": "whitenight.event/1",
  "event_id": "uuid",
  "ts": "2026-08-15T12:00:00+08:00",
  "session_id": "uuid",
  "task_id": "uuid | null",
  "channel": "web | onebot",
  "kind": "message | plan | progress | approval | result | error | aborted | heartbeat",
  "actor": "whitenight | hermes | codex | tool:<name> | user",
  "status": "running | waiting_approval | succeeded | failed | aborted",
  "progress": { "step": 2, "total": 5, "label": "提取 PDF 文本", "detail": "page 3/12" },
  "payload": {}
}
```

## 约束

- `payload` 不得包含密钥、Token、审批编号明文以外的敏感信息；审批编号是一次性短时值。
- 执行器原始输出只允许出现在 `payload.raw_artifact`，默认不渲染到聊天。
- 事件流允许乱序到达，消费方必须按 `event_id` 去重，以 `task_id + status` 终态为准。
- 中止请求是独立控制通道：`POST /api/v1/tasks/{task_id}/abort`（阶段 5 实现），
  执行器收到后必须尽快结束并发布 `aborted` 终态事件。
