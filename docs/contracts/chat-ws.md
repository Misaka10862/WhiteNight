# 流式聊天 WebSocket 契约（v0.2）

阶段 2 的 WebUI 与 API 使用一条 WebSocket 连接完成一轮聊天；连接对每个请求
保持到 `done`/`error` 事件后由客户端关闭。所有字段走 JSON，UTF-8。

## 连接

- 生产直达：`ws://127.0.0.1:8765/api/v1/chat/ws`
- 开发经 Vite：`ws://127.0.0.1:5173/api/v1/chat/ws`（`/api` 代理已启用 ws 升级）

## 客户端 → 服务端（一条消息）

```json
{
  "type": "chat",
  "session_id": "uuid",
  "text": "你好",
  "image_data_url": "data:image/png;base64,..."
}
```

- `session_id` 必须来自 `POST /api/v1/sessions`；
- 纯文字时 `image_data_url` 为 `null`；
- 图片仅支持 png/jpeg/gif/webp，最大 8 MiB（`max_image_bytes`）。

## 服务端 → 客户端

```json
{"type":"start","session_id":"..."}
{"type":"chunk","delta":"好"}
{"type":"chunk","delta":"的"}
{"type":"done","session_id":"...","message_id":"...","text":"好的","extra":{"user_message_id":"..."}}
```

错误：

```json
{"type":"error","message":"模型调用失败：..."}
```

## 语义

- 用户消息**先落库**再开始生成；只有完整 assistant 回复才落库。
- `chunk.delta` 是模型可见内容（thinking 不会透传给 WebUI）。
- `done.text` 与所有 delta 拼接结果一致；客户端以 `done` 后刷新历史为准。
- 同一连接可顺序发送多条消息；断开重连不产生重复回复，因为重连不会重放请求。
- 后续标准事件信封（任务进度/审批）沿用 `docs/contracts/event-envelope.md`。
