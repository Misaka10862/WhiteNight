# Application event envelope (whitenight.event/1)

`whitenight.events.EventEnvelope` defines the common application header. Chat transports retain
legacy fields while adding this header; delegate adapters still produce typed `DelegateEvent`
records, which the conversation layer places in a correlated chat envelope. Consumers must use
structured fields rather than infer state from executor terminal output.

```json
{
  "envelope": "whitenight.event/1",
  "event_id": "event-uuid",
  "request_id": "request-uuid",
  "session_id": "session-uuid",
  "task_id": null,
  "channel": "web",
  "kind": "message",
  "actor": "whitenight",
  "status": "running",
  "ts": "2026-09-04T12:00:00Z",
  "payload": {"delta": "Hello", "extra": null},
  "type": "chunk",
  "delta": "Hello"
}
```

## Fields and compatibility

- `event_id` identifies one emitted event. Replayed persisted terminal events retain their identity.
- `request_id` binds a conversation attempt; `session_id` and optional `task_id` correlate domain records.
- `channel` is supplied by the trusted adapter context, not by arbitrary request JSON. Current chat
  channels are `web` and `onebot`; `actor` identifies the producing application/executor.
- `kind` describes the event. Chat maps start/chunk to `message`, done to `result`, task events to
  `progress`, and uses `approval`, `tool`, `error` or `aborted` where applicable.
- `status` includes `running`, `waiting_approval`, `succeeded`, `failed` and `aborted`. A recovered
  unfinished request can return `awaiting_review`; consumers must not treat that as success.
- `payload` carries structured content. Legacy chat fields `type`, `delta`, `message_id`, `text`,
  `message` and `extra` remain available during migration. Normal streamed chat events mirror these
  content fields into payload; recovery/error terminal events retain the legacy content fields.
- Delegate details currently remain in `extra.delegate_event` and its mirrored payload entry.
  `DelegateEvent.progress` is a fraction from 0 to 1; it is not the old draft's step/total object.

## Safety and completion semantics

Credentials, database keys, recovery keys, authorization headers and private Provider error bodies
must never be embedded in an event. Short-lived approval codes are operational identifiers and may
appear only in the approval workflow. Task artifacts and document/model content are untrusted data;
none grants permission to execute tools or change policy.

An event stream is an observation channel, not the authority to grant approval. Decisions pass through
the typed approval API and its bound scope/channel/parameters. Terminal status is persisted by request
identity. Consumers should treat repeated terminal events idempotently and refresh stored history.

Cancellation uses a separate control request: `POST /api/v1/chat/{request_id}/cancel` for a conversation,
or `POST /api/v1/tasks/{task_id}/abort` for a delegated task. Delegated cancellation distinguishes
`cancelling`, verified `aborted`, and `cancel_failed`; a request to stop is not proof of termination.
