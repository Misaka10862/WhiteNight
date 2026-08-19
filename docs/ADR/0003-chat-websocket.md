# ADR-0003: Phase 2 streaming chat uses WebSocket, single request, single connection

- Status: Accepted
- Date: 2026-08-15

## Background

The architecture diagram in Section 5 of the build plan is `WebUI -> WhiteNight API / WebSocket`; Phase 2 needs to be opened up
WebUI → API → Ollama's streaming reply, and supports image and session recovery.

## decision making

1. The chat uses a WebSocket (`/api/v1/chat/ws`), and a request is streamed back within the same connection.
   `start / chunk / done / error` event, the client closes the connection after `done`.
2. No need for SSE: SSE can only be used in one direction and cannot carry the subsequent unified approval request/abortion control channel;
   The same WebSocket event model can be smoothly upgraded to standardized event envelopes.
3. User messages are persisted first, and then the complete assistant reply is dropped into the database; the request is not replayed when the connection is interrupted.
   Therefore, restarting/disconnecting will not generate duplicate replies.
4. The image is first downloaded to `data/attachments/`, and the message only stores the relative path and MIME; it is generated when reading back
   data URL, missing file returns `null` instead of fake content.
5. The transmission event only contains the visible content delta of the model; the thinking token does not exit the WebUI.

## Consequences

- Advantages: A single transport layer covers the progress, approval and abort requirements of stages 2-8.
- Cost: The client needs to manage the WebSocket life cycle; the disconnection and reconnection logic is concentrated in the Web channel layer.
- Fallback: If the server needs to actively push history/heartbeat in the future, expand the event type on the existing WS,
  No changes to the REST session interface.
