# Streaming Chat WebSocket Contract (v0.2)

Phase 2 WebUI and API use a WebSocket connection to complete a round of chat; the connection is used for each request
Keep until closed by client after `done`/`error` event. All fields are in JSON, UTF-8.

## Connect

- Production direct: `ws://127.0.0.1:8765/api/v1/chat/ws`
- Developed by Vite: `ws://127.0.0.1:5173/api/v1/chat/ws` (`/api` agent has ws upgrade enabled)

## Client → Server (one message)

```json
{
  "type": "chat",
  "session_id": "uuid",
"text": "Hello",
  "image_data_url": "data:image/png;base64,..."
}
```

- `session_id` must come from `POST /api/v1/sessions`;
- `image_data_url` is `null` when it is plain text;
- Images only support png/jpeg/gif/webp, up to 8 MiB (`max_image_bytes`).

## Server → Client

```json
{"type":"start","session_id":"..."}
{"type":"chunk","delta":"good"}
{"type":"chunk","delta":"of"}
{"type":"done","session_id":"...","message_id":"...","text":"Okay","extra":{"user_message_id":"..."}}
```

Error:

```json
{"type":"error","message":"Model call failed:..."}
```

## Semantics

- User messages are logged first and then generated; only complete assistant replies are dropped.
- `chunk.delta` is the visible content of the model (thinking will not be transparently transmitted to WebUI).
- `done.text` is consistent with all delta splicing results; the client shall refresh the history after `done`.
- Multiple messages can be sent sequentially on the same connection; disconnection and reconnection will not generate duplicate replies because reconnection will not replay the request.
- Subsequent standard event envelopes (task progress/approval) continue to use `docs/contracts/event-envelope.md`.
