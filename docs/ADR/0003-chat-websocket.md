# ADR-0003：阶段 2 流式聊天使用 WebSocket，单请求单连接

- 状态：已接受
- 日期：2026-08-15

## 背景

构建计划第 5 节架构图为 `WebUI -> WhiteNight API / WebSocket`；阶段 2 需要打通
WebUI → API → Ollama 的流式回复，并支持图片与会话恢复。

## 决策

1. 聊天采用一条 WebSocket（`/api/v1/chat/ws`），一个请求在同一连接内流式返回
   `start / chunk / done / error` 事件，客户端在 `done` 后关闭连接。
2. 不用 SSE：SSE 只能单向、无法承载后续统一的审批请求/中止控制通道；
   同一 WebSocket 事件模型可平滑升级到标准化事件信封。
3. 用户消息先持久化，完整 assistant 回复后落库；连接中断不重放请求，
   因此重启/断线不会产生重复回复。
4. 图片先落盘 `data/attachments/`，消息只存相对路径与 MIME；读回时生成
   data URL，文件缺失返回 `null` 而不是伪造内容。
5. 传输事件只包含模型可见内容 delta；thinking token 不出 WebUI。

## 后果

- 优点：单一传输层覆盖阶段 2-8 的进度、审批与中止需求。
- 代价：客户端需要管理 WebSocket 生命周期；断线重连逻辑集中在 Web 渠道层。
- 回退：如后续需要服务器主动推送历史/心跳，在现有 WS 上扩展事件类型，
  不改 REST 会话接口。
