# Provider interface contract (v0.1 draft)

All external services must be behind the Provider interface and can be replaced independently. Phase 0 only defines boundaries,
After the high-risk capability verification in Phase 1 is completed, use the actual test report to lock the version and specific semantics of each interface.

## ModelProvider

- `complete(messages, images, tools) -> AsyncIterator[ModelEvent]`: streaming text/tool call event;
- `health() -> ModelHealth`: delay, video memory, model list;
- Implementation: Ollama (Phase 1 validation `qwen3-vl:8b`) with OpenAI-compatible Chat Completions;
  Cloud credentials are only read from Keychain, still using local Ollama by default.

## SearchProvider

- `search(query) -> list[SearchResult]`: `{title, url, snippet, retrieved_at}`, retain the source;
- `fetch(url) -> FetchedPage`: Page extraction, the returned content must have a source tag, and the content is regarded as untrusted input.

## EmbeddingProvider

- `embed(texts) -> list[float]` and `health()`; load on demand to avoid competing for memory with the 8B model.

## DelegateProvider (public contract for Hermes/Codex)

- `create_session(scope, cwd) -> SessionHandle`；
- `submit(task_pack) -> AsyncIterator[TaskEvent]`: progress, approval, product, error, abort;
- `abort(session, task)`；
- `resume(thread_id)` (Codex resumable thread, Hermes session continuation).
- Adapters must not parse actuator terminal text as a source of status; upgrades only modify the corresponding adapter.

## ChannelProvider（Web / OneBot）

- `inbound -> NormalizedMessage`: Unified message `{sender, channel, kind, text, images, files, quote}`;
- `outbound(NormalizedReply)`；
- Channels are only responsible for transmission and formatting, and do not hold models, memories, permissions or personality states.

## Version discipline

- After phase 1 is completed, each running dependency record: version, commit hash, license, compatibility conclusion;
- Upstream upgrades must pass contract testing before updating `uv.lock` / `package-lock.json`.
