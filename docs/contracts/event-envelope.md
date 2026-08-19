# Standardized event envelope (v0.1 draft)

All channels, task executors and background schedulers publish this envelope uniformly. From stage 2 onwards, the `api` package is implemented according to this structure.
The WebUI to OneBot adapter relies only on envelope fields and does not parse any of the executor's raw terminal text.

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
"progress": { "step": 2, "total": 5, "label": "Extract PDF text", "detail": "page 3/12" },
  "payload": {}
}
```

## Constraints

- `payload` must not contain sensitive information other than the plain text of the key, Token, and approval number; the approval number is a one-time short-term value.
- The raw output of the executor is only allowed to appear in `payload.raw_artifact`, and is not rendered to chat by default.
- The event stream is allowed to arrive out of order, and the consumer must remove duplicates by `event_id`, and the final state of `task_id + status` shall prevail.
- The abort request is a separate control channel: `POST /api/v1/tasks/{task_id}/abort` (Phase 5 implementation),
  The executor must terminate and publish the `aborted` final event as soon as possible after receiving it.
