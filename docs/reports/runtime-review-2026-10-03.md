# Runtime and architecture review — 2026-10-03

## Scope and evidence

This review covers first-release reliability within the existing Provider, application,
policy and persistence boundaries. It does not add product capabilities or dependencies.
The source baseline is `f4b468d`; the running checkout additionally contains pending
September file-operation and deployment changes, including migration 0013. Those changes
are preserved separately. Implementation and verification use an isolated worktree.

Read-only inspection covered `data/logs/whitenight.log`, the launchd error log, runtime
configuration, aggregate audit records and memory-job state. No private message bodies,
account identifiers, signed URLs or raw logs are included in this report or committed.
No live model request, QQ message, migration or service restart was issued.

The latest available application entry was **2026-10-02 19:14:26 Asia/Shanghai**. The
September 24–October 2 window contained 224 timestamped entries: 213 INFO, 11 WARNING,
and no ERROR/CRITICAL entries. Counts refer to one application log, not the duplicated
launchd output. There were 30 inbound QQ handling entries, 17 proactive-send entries
and 151 HTTP 200 entries; HTTP success alone does not establish model-output correctness.

The 11 warnings comprise six maintenance retry warnings and five extraction warnings:
two empty outputs, two JSON decode failures and one transport `ReadError`. The remaining
maintenance warning has no preceding extraction warning and lacks stage information.
The live database held 38 memory jobs with **zero pending jobs** and zero current retry
attempts. `/healthz` returned `ok`. These observations establish recovery at inspection
time, not uninterrupted availability or proof that every extracted memory was correct.

## Architecture assessment

- `application/runtime.py` is the composition root for Providers, stores, channels and
  lifecycle management. Web and OneBot enter the shared chat service; task routing,
  tools and delegated work use explicit adapters and policy/approval checks.
- `agent/conversations.py` and persistence retain conversation identities and terminal
  events. Background memory maintenance has durable sequence checkpoints and yields
  to foreground chat. These are useful existing boundaries and do not need replacement.
- Completion and validation defects occur at the Provider-to-application boundary:
  downstream services already rely on a truthful `ModelChunk.done` and a successful
  extraction result before advancing durable state.
- Logging has a shared redaction filter, but it previously recognized assignment-style
  secrets without covering arbitrary signed URL parameters. Log viewers also read the
  whole file on the event loop and returned older unsanitized entries unchanged.

## Prioritized improvements and attribution

| Priority | Finding and evidence | Attribution | Delivered change |
|---|---|---|---|
| High | Three recent HTTP log entries retained signed download query parameters; a synthetic `rkey` URL also survived redaction | Deterministic logging defect, independent of the model | Hide URL user information, queries and fragments in both log handlers; redact historical entries when serving the log tail |
| High | A synthetic SSE stream ending after a partial delta emitted `done=True`; token-limit and in-stream error frames were also treated as success | Deterministic Provider adapter defect; historical warnings alone cannot prove which termination occurred | Validate event shapes, require an explicit completion signal and classify truncated, filtered, malformed and upstream-error responses without emitting success |
| High | `{}`, missing fields and an embedded JSON fragment advanced the extraction checkpoint as empty successful results | Deterministic schema/default interaction; malformed model output is a separate generation limitation | Require both memory arrays in a complete JSON object or one complete JSON fence; keep failure retryable and keep internal success state outside model control |
| Medium | Malformed or non-object tool JSON was silently replaced with `{}`, potentially activating tool defaults | Deterministic coercion defect triggered by bad model output | Reject the complete batch before publishing any tool calls; preserve the existing typed executor and approval boundary |
| Medium | Maintenance warnings identified only an exception class; log reads scaled with the entire file | Deterministic observability/performance gaps | Record fixed stage/reason metadata and read at most 256 KiB at the end of the file, off the API event loop |

The memory prompt now gives the exact empty-object shape and requires literal source IDs.
This improves the instruction, but does not claim to solve model reasoning, factuality or
generation reliability. The hard guarantees come from validation and durable checkpoints.
No warning bodies were retrospectively inferred from stored private conversations.

## Contract details

The OpenAI-compatible adapter accepts `[DONE]` or an explicit `stop`/`tool_calls` finish
as completion. A transport EOF alone is insufficient. `length` and `content_filter`
produce distinct bounded errors; malformed frames and tool arguments are rejected.
Usage-only chunks remain supported. Tool proposals are published together only after
the response and every argument object validate; no automatic transport retry is added.
The meaning of the finish reasons was checked against the
[official OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions).
Compatibility with the configured third-party endpoint is covered by mock contracts,
not a new live-provider acceptance run.

Memory results must contain `facts` and `episodes`; `{}` and partial envelopes cannot
mean “nothing to remember.” A valid explicit empty result still advances the checkpoint.
Invalid JSON, schema mismatches, incomplete streams and provider errors record separate
metadata, while maintenance records its stage and source/summary validation reason.
Existing retry backoff and source-message validation remain authoritative.

Log tails preserve complete UTF-8 lines within the byte budget. An oversized partial
first line is omitted because it may have lost the URL/key prefix needed for redaction.
This can return fewer than the requested lines. Historical files are not rewritten or
removed; redaction on read covers the API and diagnostics output after deployment.

## Verification

- Before implementation, 21 existing focused tests passed; 23 newly added regression
  cases failed on the original code, confirming the deterministic defects.
- After implementation, 68 focused tests passed, including real-adapter-to-memory
  checkpoint preservation, valid empty extraction, legacy-log viewing and metadata-only
  failure diagnostics. All fixtures use synthetic content and controlled transports.
- Final `PYTHONPATH=src ./scripts/check.sh`: **386 Python tests passed, 4 skipped**;
  **13 frontend tests passed**. Ruff, formatting, strict mypy (113 source files),
  credential scan, ESLint, TypeScript/Vite and technical-English audit all passed.
  The skips are the opt-in live Codex/Ollama checks and unavailable OCR. Existing
  dependency deprecation warnings remain visible. Additional final contracts cover
  usage-only stream chunks and rejection of a mixed valid/invalid tool batch.
- Shared local dependencies were reused without installing/upgrading packages or
  changing lockfiles. `PYTHONPATH=src` selects the isolated worktree's Python source. The running
  original checkout still returned `ok` after verification and its pending changes
  remain separate. Deployment and live-provider acceptance are not claimed.

## Follow-up directions

1. Add a metadata-only operational view for memory backlog, retry age and failure
   categories if failures persist. The current snapshot has no backlog; new stage/reason
   logs provide the first evidence needed to prioritize such a view.
2. Evaluate an optional structured-output capability behind `ModelProvider`, using a
   small local regression corpus and separate contracts for each configured endpoint.
   Do not infer API support or increase token budgets solely from JSON failures.
3. Run a new dated 72-hour sleep/wake and network-outage acceptance exercise, followed
   by an agreed production backup/restore drill. Historical reports do not certify
   current runtime availability. This review does not create recurring automation.
4. Review the pending September changes as their own delivery. They are active locally
   but absent from the reviewed Git baseline, which makes runtime-to-commit attribution
   harder. They are not silently bundled into this reliability commit.
