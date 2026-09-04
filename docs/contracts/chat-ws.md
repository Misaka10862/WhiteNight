# Streaming chat WebSocket contract (v0.3)

The WebUI opens one socket per conversation request. Its controller lives above individual pages
and indexes state by session/request identity, so navigating does not move an active response into
another session. JSON is UTF-8; events include the common header in `event-envelope.md`.

## Connect and upload

- Direct API: `ws://127.0.0.1:8765/api/v1/chat/ws`.
- Vite proxy: `ws://127.0.0.1:5173/api/v1/chat/ws`.
- Isolated acceptance fixture: API 8769 and WebUI 5179.
- Local Host/Origin policy applies to HTTP and WebSocket entrypoints; listening on loopback does not
  itself authorize requests from an unrelated browser origin.
- Upload a document with `POST /api/v1/sessions/{session_id}/attachments?filename=<encoded-name>`.
  Send raw file bytes, not multipart JSON. The server bounds the body and returns an `AttachmentRecord`.

## Client request

```json
{
  "session_id": "session-uuid",
  "request_id": "client-generated-request-uuid",
  "text": "Summarize this document",
  "image_data_url": null,
  "attachment_ids": ["attachment-uuid"]
}
```

The session must already exist. `request_id` is 1–64 characters; clients should create a stable UUID
per attempt. Legacy clients may omit it and receive a server-generated identity, but cannot rely on
idempotent resubmission without retaining that identity. Text is limited to 64,000 characters and a
request accepts at most eight attachment IDs. Attachment receipts must belong to the session and
are resolved by the server; a client-supplied filesystem path is not an attachment reference.

The inline image path remains compatible: PNG/JPEG/GIF/WebP data URLs are validated against
`max_image_bytes` (8 MiB by default). Provider capabilities and explicit text-only configuration
determine whether vision is available. Missing or failed attachments produce an explicit state,
not a fabricated verified source path.

## Server events

Transport content fields are shown below; every event also carries its application envelope.

```json
{"type":"start","session_id":"session-uuid","request_id":"request-uuid"}
{"type":"chunk","delta":"Hello"}
{"type":"done","session_id":"session-uuid","message_id":"message-uuid","text":"Hello","extra":{"user_message_id":"user-message-uuid"}}
{"type":"error","message":"A bounded failure description"}
```

`task`, `tool` and `approval` events carry structured progress or permission information. Provider
thinking is not streamed as visible chat. A successful completion uses `status=succeeded`; cancellation
is an error-shaped terminal event with `kind=aborted` and `status=aborted` for existing clients.

## Identity, persistence and cancellation

- Requests within one session are serialized. Independent sessions keep separate controller state.
- User input is stored before inference; completed assistant text is persisted before successful
  completion is reported. The client retains its pending user bubble until history is refreshed.
- The server fingerprints request content and trusted channel context. Reusing an ID with different
  content fails; a completed identical request returns its saved terminal event. An identical active
  or uncertain request reports its existing state and does not repeat side effects.
- Startup marks previously running/cancelling requests `awaiting_review`; it does not automatically
  re-execute them. Tool results and task/audit records remain relevant after cancellation.
- `POST /api/v1/chat/{request_id}/cancel` requests cancellation and waits for the coordinator to drain
  the in-flight task. The response indicates `aborted` or `not_running`; cancellation does not undo
  operations already completed.
- The WebUI refreshes the affected history after completion, error, cancellation or connection loss.
  It never automatically resends on disconnect, and ignores callbacks from superseded requests.
- An IME composition-confirmation Enter does not submit. Shift+Enter inserts a line break.

The API can accept sequential messages on a socket, but the current WebUI deliberately uses a single
request/socket lifecycle. Do not infer resumable token streaming from persisted terminal-event replay.
