# Provider interface contract (v0.1 draft)

All external services must be behind the Provider interface and can be replaced independently. Phase 0 only defines boundaries,
After the high-risk capability verification in Phase 1 is completed, use the actual test report to lock the version and specific semantics of each interface.

## ModelProvider

- `complete(messages, images, tools) -> AsyncIterator[ModelEvent]`: streaming text/tool call event;
  Provider-neutral `images` are base64 values plus optional MIME metadata. Ollama
  sends them on the user message's `images` field; OpenAI-compatible Providers
  translate them to Chat Completions `image_url` content parts.
- `health() -> ModelHealth`: delay, video memory, model list;
- Implementation: Ollama (Phase 1 validation `qwen3-vl:8b`) with OpenAI-compatible Chat Completions;
  Cloud credentials are only read from Keychain, still using local Ollama by default.

## TokenCounter

- `count_text(text) -> int | None` and `count_request(messages, tools) -> int | None`;
- a local `tokenizer.json` provides exact tokenizer counts without loading model weights;
- unavailable counters return `None`; they never present character-count estimates as exact tokens.

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
  OneBot quote segments are resolved through `get_msg` when available and carried
  as bounded, explicitly untrusted context; missing quote history is reported
  rather than guessed.
- `outbound(NormalizedReply)`；
- Channels are only responsible for transmission and formatting, and do not hold models, memories, permissions or personality states.

## Version discipline

- After phase 1 is completed, each running dependency record: version, commit hash, license, compatibility conclusion;
- Upstream upgrades must pass contract testing before updating `uv.lock` / `package-lock.json`.
