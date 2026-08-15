# 阶段 8 QQ 私聊（OneBot Adapter）实测报告（2026-08-15）

> 复跑：`uv run pytest`（118 passed, 4 skipped）；`./scripts/check.sh` 通过。

## 1. OneBot 11 Adapter

- 事件：HTTP POST `/api/v1/onebot/events`；只处理 private 消息，群聊一律忽略。
- 所有者白名单：`qq_owner_ids`，非 owner 直接 `ignored_not_owner`。
- 幂等去重：`message_id + user_id` 缓存（TTL 600s，上限 10k）。
- 顺序处理：按用户 asyncio.Lock 串行处理；限频默认 2s/条。
- CQ 段：text、image（base64:// 或 URL 下载）、record/file（保存 `data/qq_files`）。

## 2. 与 Core 共享状态

- 迁移 0007 `channel_sessions`：`(channel, owner_key) -> session_id`，
  QQ 与 WebUI 共享同一会话/长期记忆/任务状态。
- 聊天走 `ChatService.stream_reply`：路由、记忆异步提取、委派任务事件全部复用；
  委派 started/error 会发一条任务提示，结果在最终回复中。

## 3. QQ 内审批

- 命令：`同意 <编号>` / `拒绝 <编号>`；编号短期一次性，不可重放。
- 编号不存在/已处理/范围不匹配都会收到明确回复；审批串线测试覆盖。

## 4. 发送器

- `OneBotSender`：`send_private_msg`（按 4000 字符分片）、
  `upload_private_file`（multipart）；失败有限重试（3 次）。
- 实现 ProactiveSender 协议：阶段 8 起可把主动消息发到 QQ。

## 5. 实测

- 契约测试 8 个：白名单、群聊忽略、重复事件、图片理解、文件保存、
  审批批准/拒绝/重放、去重 TTL/限频、分片、发送重试。
- 真实 E2E：启动 mock OneBot HTTP API + WhiteNight（QQ 开启，owner 10001），
  发送 private 事件「只回复两个字：在的」→ 真实 Ollama 生成「在的」→
  mock 收到 `POST /send_private_msg {"user_id":10001,"message":"在的"}`。

## 6. 边界

- NapCat 安装与 QQ 小号登录需用户操作；当前用 mock OneBot 服务器验证链路。
- 引用消息、表情包与富媒体体验属阶段 10 后的扩展，不在首版验收范围。
