# Provider interface contract (v0.2)

External inference, search, embedding, delegation and channel delivery remain behind explicit
interfaces. Application orchestration owns identity, history, permissions and task state. An adapter's
claimed capability is a tested implementation guarantee, never a property inferred from model prose.

## ModelProvider

- `stream_chat(messages: list[ProviderMessage], tools: list[ToolSpec] | None) -> AsyncIterator[ModelChunk]`.
- `health() -> Awaitable[dict[str, object]]` returns structured availability information.
- `ModelCapabilities` declares tools and vision. Undeclared adapters default to no tool support and
  unavailable vision; an explicit deployment text-only setting still takes precedence.
- `ProviderMessage` includes role/content, base64 images with MIME metadata, tool calls, tool-call ID
  and name. Ollama serializes image arrays; OpenAI-compatible adapters serialize `image_url` parts.
- `ModelChunk` carries visible delta, internal thinking, validated tool-call records and a done marker.
  Tools are proposals only: the application validates parameters and policy before execution.
- Provider failures use bounded metadata such as category, HTTP status and an error ID. Credentials
  and upstream response bodies must not be copied into user-visible errors or diagnostic logs.

## TokenCounter

`available`, `count_text(text) -> int | None`, and `count_request(messages, tools) -> int | None`
provide optional local tokenizer counts. A local tokenizer asset loads independently of model weights.
Unavailable counters return `None`; a character budget must not be labelled an exact token count.

## SearchProvider

- `search(query, limit=8) -> list[SearchResult]` returns title, URL, snippet and retrieval time.
- `fetch(url, max_chars=12000) -> FetchedPage` returns source/final URL, title, bounded text and truncation
  status. Fetched content remains explicitly untrusted; redirects and addresses are validated.
- Synchronous network work is invoked through bounded worker execution, not on the async event loop.

## EmbeddingProvider

`embed(texts: list[str]) -> list[list[float]]` is the required synchronous method. Implementations
may expose a cache identity tied to Provider/model revision. Embeddings are maintained outside
interactive retrieval, with persistent versioned cache records and lexical fallback on unavailability.
No universal `health()` method is implied by this protocol.

## DelegateProvider

- `name` and `DelegateCapabilities(read_only, action_policy)` declare enforceable capabilities.
- `health() -> Awaitable[dict[str, object]]` reports structured status.
- `submit(DelegationRequest) -> AsyncIterator[DelegateEvent]` reports queued/started/progress,
  approval-required/artifact/result/error/aborted events through typed records.
- `abort(task_id, thread_id=None) -> Awaitable[bool]` returns true only after execution is verifiably stopped.
- Requests include task ID, prompt, working directory, optional thread ID/sandbox and metadata.
  A thread ID field is not a promise that every adapter can safely resume arbitrary prior tasks.

Codex currently supports only newly created read-only sandbox tasks after an explicit `/codex` request.
Write delegation is rejected because the adapter does not establish WhiteNight per-action approval,
parameter binding and unconditional batch-delete refusal. Existing Codex threads with unverified
sandbox permissions are not resumed. Native sandbox prompts alone do not establish `action_policy`.

Hermes remains disabled by default. Enabling/authenticating it does not bypass capability checks;
real submission/approval/cancellation contracts still require validation. Unknown-effect failures
remain uncertain rather than triggering automatic retries. Cancellation distinguishes requested,
verified stopped and failed-to-stop states. No adapter parses terminal prose into authority or status.

## Channel and delivery boundaries

`ChatRequest`, `AttachmentRecord` and trusted `ChannelContext` normalize Web/OneBot input. OneBot
quote messages become bounded untrusted context; server-resolved attachment receipts carry status,
MIME, size and hash. Channel identity and delivery targets are established by the adapter, not model arguments.

`FileDeliveryProvider.upload_file(target, path, name)` and
`StickerDeliveryProvider.send_sticker(target, sticker_id)` are explicit outbound interfaces.
Transmission/formatting adapters do not own models, memory, personality or permission policy.
Owner-only and approval requirements apply equally to locally executed and delegated actions.

## Version discipline

Record versions, commit identifiers where applicable, licenses and compatibility conclusions before
changing dependencies. Contract tests must pass before changing locked packages or advertising a new
Provider capability. Test Providers and protocol mocks do not establish live external-service acceptance.
