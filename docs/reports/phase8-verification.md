# Phase 8 QQ private chat (OneBot Adapter) actual test report (2026-08-15)

>Rerun: `uv run pytest` (118 passed, 4 skipped); `./scripts/check.sh` passed.

## 1. OneBot 11 Adapter

- Event: HTTP POST `/api/v1/onebot/events`; only handles private messages and ignores group chats.
- Owner whitelist: `qq_owner_ids`, non-owner directly `ignored_not_owner`.
- Idempotent deduplication: `message_id + user_id` cache (TTL 600s, upper limit 10k).
- Sequential processing: Serial processing by user asyncio.Lock; frequency limit defaults to 2s/bar.
- CQ segment: text, image (base64:// or URL download), record/file (save `data/qq_files`).

## 2. Share state with Core

- Migration 0007 `channel_sessions`: `(channel, owner_key) -> session_id`,
  QQ shares the same session/long-term memory/task state with WebUI.
- Chat Service `ChatService.stream_reply`: Routing, memory asynchronous extraction, and delegated task events are all reused;
  Delegating started/error will send a task prompt, and the result will be in the final reply.

## 3. Approval within QQ

- Command: `Agree <number>` / `Reject <number>`; the number is short-term and one-time and cannot be replayed.
- If the number does not exist/has been processed/the range does not match, you will receive a clear reply; approve the thread test coverage.

## 4. Transmitter

- `OneBotSender`: `send_private_msg` (sharded by 4000 characters),
  `upload_private_file` (multipart); limited retries on failure (3 times).
- Implement the ProactiveSender protocol: active messages can be sent to QQ from stage 8 onwards.

## 5. Actual measurement

- 8 contract tests: whitelist, group chat ignore, repeated events, image understanding, file saving,
  Approval/rejection/replay, deduplication TTL/frequency limiting, fragmentation, sending retry.
- Real E2E: start mock OneBot HTTP API + WhiteNight (QQ is turned on, owner 10001),
  Send private event "reply only two words: in" → real Ollama generates "in" →
The mock received `POST /send_private_msg {"user_id":10001,"message":"\\u5728\\u7684"}`.

## 6. Boundary

- NapCat installation and QQ account login require user operations; the mock OneBot server is currently used to verify the link.
- Quote messages, emoticons, and rich media experiences are extensions after Phase 10 and are not included in the first version acceptance.
