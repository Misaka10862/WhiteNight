# WhiteNight build progress (procedural documentation)

> This file is updated with each build: recording completed, incomplete, issues and next steps.
> Build outline: `buildplan.md`. Phase conclusions and measured evidence can be found in `docs/reports/`.

Last update: 2026-09-04 (architecture hardening implemented and verified)

## 2026-09-04 architecture hardening

- The accepted implementation plan retains a single process and introduces incremental
  application boundaries, durable state, storage maintenance and behavioral regression gates.
- Diagnosis: the review found deterministic storage rollback, approval, browser origin,
  error disclosure, delegate lifecycle, async I/O, memory coverage and attachment state defects.
  Dependent tool calls may originate in model planning, but require deterministic scheduling.
- Baseline: 241 passed, 4 optional integrations skipped; static backend/frontend checks pass.
- Evidence and final verification are tracked in `docs/reports/project-review-2026-09-04.md`.
- Existing LoRA pause, opt-in Hermes, explicit `/codex` routing and disabled hosted Actions remain.
- Stages A–E are implemented: locked/journaled SQLite and SQLCipher maintenance; bound approvals;
  correlated request state; bounded tool and memory execution; structural attachment receipts;
  modular application/configuration services; scoped WebUI streams, file uploads and backup UI.
- Final unified gate: **332 passed, 4 skipped**, **13 frontend behavior tests passed**;
  Ruff, formatting, strict mypy (113 source modules), TypeScript/Vite, secrets and English checks pass.
- Real browser acceptance passed against the isolated fixture for session/page changes,
  cancellation, authorization scope, files, backups, model failures and service disconnects;
  desktop/narrow screenshots remain in the ignored data directory. No production service restart,
  private-data restore, real outbound message or paid model/agent task was performed.
- Additional deterministic integration fixes: terminal-event CAS, repeated cancellation drain,
  restore commit uncertainty, portable attachment paths and versioned Keychain configuration.
- This delivery includes the previously pending QQ/sticker implementation baseline. The unrelated
  pre-existing SOUL.md edit remains uncommitted. One final English commit/push is the delivery policy.

The entries below preserve dated historical measurements. Older references to "this round",
an ongoing monitor or a former stage completion do not supersede this summary or FINAL_STATUS.md.

## 2026-09-03 QQ file-move recovery

- **Diagnosis (two causes):** the live OneBot log showed that `AdobeAnimateEditor.exe`
  (94 MiB) exceeded the 16 MiB QQ receive limit, so no verified local source was created.
  The model then retried an unchanged move call, and the orchestration layer turned that
  recoverable model behavior into a duplicate-tool-call runtime error. The
  missing attachment-state handoff and the fatal duplicate-call handling were deterministic
  program defects; the repeated call itself is a small-model capability boundary.
- Failed QQ file receipt is now persisted as explicit session context and reports a precise
  size-limit/retry message. A request to move that unavailable attachment is stopped before
  model inference, so it cannot invent a source path. Repeated identical tool calls now receive
  a structured refusal result and let the model recover; tool parameters still pass through the
  existing type, policy, and approval layers.
- Verification: focused file-tool, chat-tool, and OneBot tests pass (**54 passed**); Ruff and
  strict mypy pass for the changed source modules.
- Follow-up diagnosis: a later 946 KiB attachment was saved correctly and `pvzHE` existed, but
  the model emitted prose without calling `file.move`; no move audit or approval was created.
  Explicit recent-attachment moves to a server-resolved directory now create the normal
  `file.move` approval deterministically before model inference. Full verification after this
  follow-up passed: **241 passed, 4 skipped**, with Ruff, mypy, frontend checks, and the
  technical-English audit all clean.

## 2026-09-03 QQ native custom-face binding

- **Diagnosis (deterministic integration mismatch):** the running NapCat account emits saved
  personal custom faces as `image` segments with `sub_type=1`; the previous implementation only
  emitted the marketplace `mface` segment and the runtime catalog still referenced stale
  `sticker-01.png` files. This is a protocol/catalog mismatch, not a model capability issue.
- Added `OneBotSender.send_private_sticker()` for NapCat's personal-face transport. It sends the
  registered QQ URL with `sub_type=1`, which QQ renders as its animated-face type; marketplace
  `mface` delivery is retained separately.
- Added `scripts/sync_qq_stickers.py`, which binds the 18 local assets to QQ's saved-face remarks
  via `fetch_custom_face_detail`, and refreshed the local runtime catalog. The model still sees
  only labels and stable IDs; delivery remains owner-only, policy-audited, one-per-turn, and after
  the final text.

## 2026-09-02 README synchronization

- Synchronized the English README with the updated Chinese version, including the broader product
  positioning, `qwen3` wording, post-AGI long-term vision, and operating-system/chat-platform
  roadmap. Corrected minor Chinese capitalization and spacing in the roadmap; no code or dependency
  changes were made.

## 2026-09-02 Mixed sticker sheet preparation

- Created a separate nine-image set on the Desktop from the two supplied sheets using the
  row-major selection `112121122`; the original sticker set was not modified.
- Removed the top-center extra ear from image-1 cell 6 by masking only that protrusion and
  preserving the transparent background. Native QQ identifiers still need to be registered
  and added to the new catalog before delivery is enabled.

## 2026-09-01 QQ outage diagnosis and emotion stickers

- **Diagnosis (external service outage, not a model capability limit):** WhiteNight remained
  healthy and its database/model calls were available.  The 05:58 shutdown followed by the
  06:03 launchd start was a clean lifecycle restart with no crash traceback.  The current QQ
  failure is NapCat/OneBot `127.0.0.1:3000` connection refusal; the NapCat process is not running.
- Added structured OneBot health details to `/api/v1/system/health` and `/api/v1/onebot/status`.
- Added a validated local sticker catalog, deterministic transparent 3×3 importer, and the
  policy-gated `channel.sticker.send` tool.  QQ replies can now send at most one catalog sticker
  after the final text response; image delivery is audited without storing image bytes or paths.
- Imported the supplied 1254×1254 RGBA sheet into `data/stickers/` as nine cropped PNGs with
  editable labels in `catalog.json`. Native QQ delivery now requires per-sticker NapCat/QQ
  identifiers (`emoji_id` plus `emoji_package_id` or `key`); PNG-only records are intentionally
  not sent as images. The previous PNG delivery path was removed, so QQ will never render these
  records as ordinary image messages.
- Pillow `12.3.0` is now declared directly (already present in the lock through python-pptx);
  the package remains under its HPND license and no version upgrade was performed.

## 2026-08-29 QQ images and reply-context repair

- **Diagnosis (deterministic program defects, not an 8B capability limit):** the
  active `deepseek-v4-flash-vision-exp` OpenAI-compatible provider was blocked by
  the stale text-model `model_supports_vision=false` gate.  If that gate were
  bypassed, `OpenAIProvider` still discarded `ProviderMessage.images` instead of
  serializing Chat Completions `image_url` content parts.  QQ input could also
  silently lose a NapCat local-cache/file-id/CQ-string image; failed URL downloads
  degraded to text.  These failures occurred before a multimodal model received
  an image.
- The model Provider now advertises its own visual capability (`qwen3-vl`/vision
  Ollama models and OpenAI-compatible vision requests), while an explicit
  text-only configuration still wins.  OpenAI-compatible requests serialize each
  inbound image as a data-URL `image_url` part and preserve PNG/JPEG/GIF/WebP MIME.
- The OneBot adapter now accepts HTTP URLs, `base64://`, local NapCat image cache
  files, file IDs (via `get_image` then `get_file` fallback), and legacy CQ-string
  message payloads.  Every source is size/type checked before the core sees it;
  unreadable images receive an explicit QQ error instead of an invisible text-only
  fallback.
- **QQ reply-message diagnosis (deterministic program gap):** `reply` segments
  were parsed as neither text nor context, so the model had no information about
  the message being answered.  The adapter now resolves the quoted `message_id`
  through OneBot `get_msg`, inserts bounded original text with an explicit
  untrusted-context marker, and reports unavailable quotes without fabricating
  their contents.  Remaining reply quality after the original text is supplied is
  a normal model-understanding limit, not a missing-channel-data issue.
- Verification: focused Provider/OneBot/context tests plus full `uv run pytest`
  passed: **226 passed, 4 skipped**.  Ruff and strict mypy pass.

## 2026-08-29 Dashboard Provider and proactive delivery repair

- Added a Dashboard Provider form with the required Ollama/OpenAI-compatible choice, model/Base URL fields, Keychain-only API-key entry, immediate runtime switching and persisted non-secret configuration.
- Added a “Fetch” action beside the model name. It queries Ollama `/api/tags` or an OpenAI-compatible `/models` endpoint and lets the user choose from returned model IDs without persisting a temporary API key.
- Diagnosed and fixed cloud chat 400 responses: DeepSeek rejects dotted internal tool names such as `file.find`; the OpenAI-compatible adapter now maps tool names to the provider-safe `[A-Za-z0-9_-]+` grammar in both directions, including follow-up tool messages. This was a deterministic program defect, not an 8B model capability issue.
- Added a launchd-scoped “Restart WhiteNight service” action with explicit rejection when the backend is not launchd-managed.
- Diagnosed proactive delivery: messages were generated successfully but the configured sender defaulted to `log`, so they never reached QQ. The current local runtime is now configured for `proactive_sender: qq`; missing QQ prerequisites no longer silently fall back to logs.
- Proactive delivery status is visible in the WebUI. New delivery records contain only metadata (timestamp, target, result, retry count, length/hash), never message bodies; historical logs are retained.

## 2026-08-29 WebUI availability repair

- Diagnosed Dashboard unavailability as the Vite process exiting while the backend
  launchd service remained healthy (`8765` reachable, `5173` not listening).
- Added `deploy/com.whitenight.web.plist.template` and
  `scripts/install_webui_launchd.sh` so the local Vite server runs as an independent
  `com.whitenight.web` user service with `RunAtLoad` and `KeepAlive`.
- Kept the backend service, database, and existing source behavior unchanged; verified
  the WebUI HTML, `/api` proxy, and browser-rendered navigation after recovery.

## 2026-08-26 personality and context compiler

- Added native CCv2/V3 character cards, the single local-user Persona, live revisions, archival,
  session-bound roles, selectable greetings, JSON/PNG round trips and deterministic QQ role
  switching. Existing data migrates to the default Xiaobai character.
- Added the pinned prompt compiler, safe macro allowlist, advanced custom blocks, prompt preview,
  generation manifests, optional local tokenizer counting, and bounded high-compatibility lorebook
  activation with reproducible probability and persistent timed effects.
- Closed the deterministic memory integration gap: facts and episodes are character-scoped,
  conflict/deleted values are excluded, summaries and retrieval are injected as sourced data, and
  delayed extraction uses durable sequence checkpoints.
- Added reversible migrations 0009/0010. A version-changing SQLite upgrade first creates and
  integrity-checks a recoverable database copy; upgrade/downgrade tests preserve old messages and
  memory bodies.
- License conclusion: no SillyTavern AGPL source is copied or linked. Public card formats and
  observable behavior are implemented independently; dependency review is recorded under
  `docs/reports/personality-dependencies.md`.

## 2026-08-24 maintenance

- Fixed incoming QQ file downloads when NapCat reports only a display name plus `file_id`. The OneBot adapter now resolves trusted file metadata through `get_file`, then accepts only a regular local file, HTTP(S) URL, or validated base64 payload under the existing 16 MiB receive limit. This prevents the display name from being mistaken for a local path.
- Preserved the latest verified QQ attachment path across follow-up file operations and Hermes/Codex delegation. Delegate tasks now receive an absolute working directory plus a server-generated attachment context, so phrases such as "the file I just sent" do not cause the target folder name to be searched as the source file.
- Fixed managed Hermes 0.17 WebSocket authentication by sharing an in-memory process token between the child process and `/api/ws`. When no cloud credential exists, the managed Provider uses the installed local `qwen3-vl:8b` through Ollama's OpenAI-compatible endpoint; a real structured delegation returned `HERMES_OK`.
- Fixed Codex MCP task calls incorrectly inheriting the 60-second startup timeout and added current structured-result parsing. MCP tool failures such as the observed Cloudflare 403 are now failures rather than successful task results. The MCP handshake and tool discovery pass; the configured user-level `AI-MEMBER` upstream remains externally blocked by Cloudflare and must be restored or replaced by its owner.
- Added a mandatory pre-fix diagnosis rule to `AGENTS.md`: every bug must first be classified as a deterministic program defect, an 8B-model capability limit, or both, using logs/audits/tests/minimal reproduction before implementation changes.
- File-move diagnosis: the program stored incoming QQ attachment paths as relative paths and allowed impossible destinations to reach approval; the 8B model then guessed the wrong absolute source, treated a directory as a complete destination, and retried after an approval reply omitted its one-time code. The adapter now stores absolute attachment paths, local and delegated models receive a server-verified source path, directory destinations preserve the original QQ filename, and nonexistent destination parents are rejected before approval. QQ approval replies without a code now receive deterministic guidance, and expired approvals are excluded from pending operations.

## 2026-08-23 maintenance

- Fixed the managed Hermes WebSocket adapter so gateway disconnects and protocol failures are normalized to `DelegateError` instead of escaping the delegate retry boundary. Managed startup no longer requires a DeepSeek key when Hermes uses its own logged-in provider credentials.
- Added the Volcengine Doubao Search Global Provider behind the existing `SearchProvider` interface. The API key is stored in macOS Keychain account `volc_search_api_key`; requests use `https://open.feedcoopapi.com/search_api/global_search` and preserve source URLs/snippets as untrusted web results. Missing credentials fall back to DDG Lite/Bing.
- Restored the missing per-user `com.whitenight.service` launchd installation after a QQ file request exposed that NapCat was online while the WhiteNight HTTP service was not running. The installed service uses the reviewed project template with `RunAtLoad` and `KeepAlive`; `scripts/check_service.sh` passed against the relaunched backend.
- Upgraded `file.find` with explicit recursive search, exact-first fuzzy matching, ranked candidates, expected-count tracking and bounded result metadata. QQ file delivery now stops before upload when the candidate count is ambiguous, asks the user to choose by number/name/path, and recognizes the immediately following selection as a current delivery request.
- Corrected location-aware file discovery after a real QQ request for the `Desktop/new_trial` folder was incorrectly rooted at the WhiteNight project directory. The service now resolves standard user-directory hints itself and overrides model-supplied `file.find.root`; fuzzy scoring rejects short-stem containment and wrong-extension false positives such as `d.py`/`methods.js` for a requested DOCX.
- Verification: real Volcengine search returned one result; `./scripts/check.sh` passed with 169 passed / 4 skipped.

## Current stage

- **File tool loop repair (this round)**: provider-native tool calls from the same model turn now run
  concurrently, with validated results returned in original call order. Trusted OneBot file delivery
  no longer asks for a second confirmation; the server still binds the recipient and verifies the
  canonical path, regular-file status, size limit and SHA-256 immediately before upload. Other
  state-changing file operations keep their existing approval levels. The immutable system safety
  appendix now also requires file intents and short follow-ups such as "send it" to complete through
  real tool results, and forbids claiming success or future execution in place of a tool call. The
  orchestrator now enforces that contract: a file-delivery turn cannot finish until every file found
  in that turn has a successful `channel.file.send` result; if a small model only promises to send,
  the validated find results are completed through `ToolExecutor`. QQ `/clear` rotates to a fresh
  context while retaining the old session for debugging and audit. NapCat file delivery uses its
  verified JSON + `base64://` contract so the QQ process never needs permission to read the original
  Desktop path; client/business errors fail once instead of triggering duplicate uploads. OneBot
  `message_sent` echoes and empty events are ignored, and the outbound-file tool is advertised and
  executable only for a current request with explicit file-delivery intent, preventing history replay.

- **Minimal Authentication Scheme (User Confirmation)**: LoRA training suspended; temporary use of native `qwen3:8b`
  Text model + SOUL.md presets the personality to pass the minimum verification; then the model with visual ability will be trained according to the formal plan.
  `scripts/e2e_smoke.py --real-model` passed the actual test (streaming chat/memory/active state/backup).
- **NapCat + QQ real link has been opened**: QQ account has scanned the code to log in (QQ restarted with `--no-sandbox`,
  WebUI 6099 / OneBot HTTP server 3000 is online). NapCat network configuration is complete:
  The HTTP client reports WhiteNight `http://127.0.0.1:8765/api/v1/onebot/events`;
  HTTP server `127.0.0.1:3000` for WhiteNight to send `send_private_msg`.
  WhiteNight has been configured `qq_enabled=true` + owner whitelist (QQ number is only kept locally
  `config/whitenight.yaml`, not written to this repository), the backend has been restarted to take effect.
Actual test: `qq_link_check.py` outputs `QQ LINK READY`; real QQ receives two messages - direct test
  (OneBotSender) Closed-loop reply to simulated private chat events via "Adapter → Session → qwen3:8b → Reply to QQ";
  `get_friend_msg_history` Review delivery. `proactive_sender: qq` is now active for the local runtime;
  the Dashboard reports OneBot reachability and does not silently fall back to log delivery.
- **Final audit (this round)**: `scripts/diagnostics.py --json` all green (DB integrity/alembic 0007,
  Ollama, Codex CLI, Hermes Gateway, disk/attachment); `scripts/e2e_smoke.py --real-model`
  Output `E2E SMOKE OK (real-ollama)`; `./scripts/check.sh` 142 passed / 4 skipped All green;
  `docs/FINAL_STATUS.md` has been synchronized to the current real status (QQ completed, 72h in progress, remaining user operation list).
- **Reply delay optimization (this round)**: Ollama's default 5m idle uninstallation causes the next message to be cold-started ~17s;
  `ollama_keep_alive` configuration has been added. **No longer a hard-coded default**: WebUI "Model and Agent"
  The page can be scrolled down to select `-1/5m/30m/1h/6h/12h`, `GET/PUT /api/v1/model/config` will be updated immediately
  Running Provider and write `config/whitenight.yaml` (automatic backup before writing), restart and persist.
  QQ closed-loop actual test "event→reply back" 4.5s; `ollama ps` displays `UNTIL: Forever`.
  Cost: qwen3:8b is resident at about 5.6GB; if you need to release it, select 5m or `ollama stop qwen3:8b` in the Dashboard.
- **Inspection Audit (Current Round)**: Check the operation records from the afternoon of 2026-08-15 to now. 72h inspection 666 checks /
  0 failures; DB integrity ok; diagnostics all green; no process crashes, Ollama’s killed alarm
  They are all proactive operations to repair runaway generation. Discovered and fixed: Backend memory retrieval used up 2048 tokens (actual test single time
  Accounting for 2 minutes and 3 seconds of inference slot) → Extract a separate limit of 512 tokens + delay 15s + cancel immediately when new messages arrive,
  The measured extraction dropped to 1.1s/209 tokens. Added `scripts/keep_awake.sh` to prevent sleep and keep alive when connected to power.
- **QQ poke recognition (this round)**: NapCat will report "poke" as a `type: "poke"` message segment,
  The text is empty; the old logic passes it to the model as an empty message, and the Dashboard displays "(empty message)".
Now `parse_segments` recognizes poke segments and injects explicit context "(The master just poked me on QQ,
  Type: xxx)", the model can generate unique responses for being poked, and there are also visible records in the session.
  At the same time, the business log loss after startup is fixed: Alembic `fileConfig` will disable the business logger/replacement
  root handler; `uvicorn log_config=None` + reset logs after migration + `disable_existing_loggers=False`.
  The actual measurement log shows `poke=True text=''`, 140 passed / 4 skipped.
- **Ollama is generated out of control (the root cause has been fixed)**: QQ's two "no replies" are not memory or Ollama's suspended animation,
  Instead, qwen3:8b has an occasional degradation cycle - the request does not set `num_predict`, and the measured single generation ran to
  `n_decoded > 4000` still does not end, occupying the only inference slot. Fix: Ollama Provider added
  `model_max_output_tokens` (default 2048) → `/api/chat` `options.num_predict`;
  The contract test locks the payload; the real QQ closed-loop self-test replies "upper limit repair completed". See question 12 for details.
- **72 hours continuous operation**: In progress (launched at 2026-08-15T08:42Z); currently 666 checks / 0 failures.
  70 >5.5 min slots matched with `pmset` sleep records (every ~15 min Maintenance on battery power
  Sleep), not an application fault; QQ cannot reply immediately during sleep, but can be used when connected to the power supply
  `scripts/keep_awake.sh start` Keep alive.
  During this period, 30 rounds of load smoke were added (passed in 4.55s), and the service remained stable.
- **Visual Return**: Native Microsoft Edge headless complete desktop 1280×900 and narrow window 480×800 screenshots,
  DOM verification All 11 navigation pages/chat input/aria tags are rendered; screenshots are saved in `/tmp/wn-*.png`
  (The current model cannot read images, and manual viewing of screenshots is done by the user).

## Completed

### Phase 0 · Project initialization ✅
- uv + Python 3.12, React/Vite/TS front-end, dependency lock, ruff/mypy/pytest, CI (no model)
- Configuration layering, Keychain, SQLCipher/Alembic, log desensitization, ADR, contract documents, SOUL/AGENTS
- Git：`bcb46a2`、`4a365d5`；tag `phase-0`

### Phase 1 · High Risk Proficiency Testing ✅
- qwen3-vl:8b text 2.2s / visual content 11.5s / tool call Schema passed; pictures must be attached message
- Hermes Gateway is bootable; cua-driver 0.19.3 is installed (TCC pending user authorization)
- Codex MCP stdio handshake passed; SQLCipher/Keychain prototype passed
- Git: `4b0ee79`, `5656a07`; report `docs/reports/phase1-verification.md`

### Phase 2 · Minimal vertical link ✅
- Unified Messaging/Session + Migration 0002; ModelProvider/Ollama Streaming; SOUL Context Budget
- `/api/v1/chat/ws` streaming chat + image attachment + session persistence; WebUI chat/upload/restore
- Actual test restart recovery and Vite proxy link; ADR-0003, `docs/contracts/chat-ws.md`
- Git：`a302d0c`

### Phase 3 · Tools, Files & Documentation ✅
- PolicyEngine/one-time approval/session authorization/audit + migration 0003; ToolExecutor only entrance
- File reading and writing, mobile wastebasket deletion, screenshots, search (DDG Lite + Bing), page extraction
- Text/code, PDF (scanned page OCR), DOCX/XLSX/PPTX, image Apple Vision OCR, zip/tar list
- 70 tests (including permissioned red teaming); report `docs/reports/phase3-verification.md`
- Git：`1e5af82`

### Stage 4 · Long-term memory ✅ (this round)
- Three-tier model: profile_facts/episodic_memories/session_summaries + migration 0004 (FTS5 + triggers)
- MemoryService: deduplication, conflict detection, immediate invalidation of old values after editing, deletion, and export to JSONL/Markdown
- Extractor: Ollama (strict JSON) + rule fallback + asynchronous extraction after main reply (no blocking chat)
- Hybrid recall: FTS5 lexicon + embedding interface + time decay + access bonus; embedding model is loaded on demand
- REST API: facts/episodes CRUD, conflict resolution, retrieve, extract, export, summary
- 87 passed / 3 skipped; the real Ollama extracts `Residence: Hangzhou`, `Hobby: Walking on rainy days` and can recall it lexically
- Report: `docs/reports/phase4-verification.md`

### Phase 5 · Routing and Agent Delegation ✅ (this round)
- Routing: Rule priority (user-specified/picture/code/GUI/memory/search/file) + optional LLM structured output + local security
- Golden routing set `evals/routing/golden.jsonl` (16 examples), target accuracy ≥ 0.9, passed the actual test
- Unified delegation events (started/progress/result/error/aborted) + DelegateProvider protocol
- Codex MCP Adapter: stdio JSON-RPC, initialize/tools, codex/codex-reply thread continuation,
  Sandbox workspace-write, approval policy on-request; real handshake test passed
- Hermes Gateway Adapter: health/authentication contract; submit fails safely and quickly before the user logs in to the Provider
- DelegateManager: task persistence (migration 0005), limited retry, abort, unavailable fast failure;
  Delegation failure after ChatService integration does not destroy the main session (in actual testing, local chat can continue)
- Task API: /api/v1/tasks list/details/aborted
- 97 passed / 4 skipped
- Report: `docs/reports/phase5-verification.md` (completed with submission)

### Stage 6 · Complete WebUI ✅ (this round)
- Workbench navigation: Chat/Session/Memory/Task/Approval/Permissions/Model/Active/Log/Backup; character/persona editing lives on the Characters page
- Chat page: conversation list, streaming bubbles, pictures, delegated task event bubbles; conversation page: rename/export/delete
- Memory page: retrieval, fact addition, modification and deletion, conflict retention/discard, episodic memory, JSONL/Markdown export
- Task page: Performer/Status/Risk/Product/Error/Abort; Approval page: Risk/Parameter Summary/Allow/Deny
- Permission page: Tool risk rules + session authorization revocation; Model page: DB/Model/Hermes/Codex Health
- Active message/log/backup page: honest occupancy (capabilities are accessed in stages 7/10 respectively, no false switches are made)
- Backend supporting API: session rename/delete/export, approvals approve/reject, policy rules/grants,
  and system health; 102 passed / 4 skipped
- Narrow window responsive layout + keyboard Enter to send + navigation/aria tag
- Actual test: full link of session/memory/task/approval/permission/model under Vite agent + real Ollama streaming chat passed
- Report: `docs/reports/phase6-verification.md`

### Stage 7 · Backend services and proactive behaviors ✅ (this round)
- Migrate 0006 proactive_state: frequency/quiet/pause/recent activity/recently sent/next candidate persistence
- Poisson scheduling: exponential interval + silent period + recent activity suppression + no reissue after expiration (sleep/disconnection safety)
- ProactiveService: candidate generation, message combination (personality + long-term memory), limited retries, log sender
- The background loop runs with the API life cycle (30s tick), and closing the WebUI does not affect the service.
- Chat user messages automatically record recent activities; active message API: status/config/pause/resume
- WebUI active message page is upgraded from placeholder to real configuration page
- launchd: plist template + install/check script; menu bar status entry Swift source code has been compiled and verified
- 110 passed / 4 skipped; real service API passed the actual test
- Report: `docs/reports/phase7-verification.md`

### Stage 8 · QQ Private Chat (OneBot Adapter)✅ (this round)
- OneBot 11 private message event/CQ segment parsing; HTTP event receiving + OneBot API sending
- Owner QQ whitelist, message_id idempotent deduplication, lock processing in user order, frequency limiting
- Text/image (base64 and URL download)/file receive and save; reply is divided into 4000 characters
- Approval within QQ: `Agree/Reject <number>`, one-time number cannot be replayed, non-owner/group chat will ignore
- Channel → Session Mapping (Migration 0007): QQ and WebUI share sessions/memories/tasks
- Limited retry on sender failure; ProactiveSender protocol adaptation (QQ active messaging available from stage 8)
- 8 contract tests; real E2E: mock OneBot API + real Ollama, event → reply → send_private_msg
- NapCat real deployment completed: QQ account login, HTTP reporting/sending network configuration, owner whitelist,
  Both the direct test and the simulated event closed-loop test passed (`QQ LINK READY`)
- Report: `docs/reports/phase8-verification.md`

### Stage 9 · LoRA personality solidification - user decision to suspend (temporary alternative)
- Offline tool chain remains ready (data specification/validation/training configuration/blind test script).
- A reproducible 600-sample candidate corpus is prepared locally: 550 general and 50 isolated
  adult-consensual samples across all nine required categories. Corpus text remains Git-ignored;
  the committed manifest contains only counts, provenance, license review, and review status.
- Candidate validation accepts `reviewed=false`; the training gate rejects every sample until the
  user records final acceptance. No candidate is currently training-ready.
- **User Instructions**: Suspend the training first and use the local `qwen3:8b` text model + SOUL.md personality run-through minimum verification.
- The code uses the default `model_name=qwen3:8b`; visual capability is now inferred from the
  selected Provider unless an explicit text-only override is configured;
  The picture message will clearly state that "the temporary text model cannot be viewed for the time being" instead of being misinterpreted.
- To be official LoRA: switch back to `qwen3-vl:8b` + `model_supports_vision=true`, and then train/blind test again.

### Phase 10 · Release reinforcement - core completed ✅, long-term testing awaiting users
- Encrypted backup/restore: WNBK1 + PBKDF2 + Fernet; SQLite online backup + attachments;
  verify/preview/restore (denial of service operation before recovery, automatic safe backup and failure rollback)
- Actual measurement: temporary library backup → preview → restore and replace; the real encrypted backup of the dev library is 9.9KB and verify/preview passes
- Diagnostic script `scripts/diagnostics.py` (DB Integrity/Migration/Disk/Provider/Pending Approval/Log)
- Log storage `data/logs/whitenight.log` (write desensitization) + `/api/v1/logs` + WebUI log page
- Load smoke `scripts/load_smoke.sh`; 72h inspection `scripts/run_72h.py` (to be executed by the user)
- Security red team supplement: prompt injection does not change the rules, web.fetch SSRF protection, evals/security golden set
- Performance smoke (session/context/retrieval/route relaxed thresholds) with `scripts/e2e_smoke.py`
  (Both dummy and real-ollama modes pass)
- `docs/INSTALL.md`、`docs/OPERATIONS.md`、`docs/RELEASE_CHECKLIST.md`
- 132 passed / 4 skipped (including backup and recovery, log API, security red team, performance)
- Report: `docs/reports/phase10-verification.md` (completed with submission)

## Not completed (by build plan stage)

| Stage | Content | Status |
|---|---|---|
| 5 | Structured routing, Hermes/Codex Adapter, task/progress/approval/abort events, upgrade retries | ✅ Core completed |
| 6 | Complete WebUI (memory/task/approval/permission/model/rules page) | ✅ Core completed (active/log/backup for honest placeholders) |
| 7 | launchd background service, Poisson active message scheduling | ✅ Core completed (real sender QQ in stage 8) |
| 8 | QQ private chat (OneBot Adapter + NapCat) | ✅ Completed (real QQ link has been tested) |
| 9 | LoRA personality solidification | ⚠️ Offline tool chain ready; training requires GPU + user blind test |
| 10 | Release reinforcement (72h, backup and recovery drill, documentation) | ✅ Core completed; 72h/blind test waiting for users |

Known gaps within the stage:
- Wiring between chat model tool_calls and ToolExecutor (belongs to stage 5)
- Backup/restore interface and encrypted backup implementation (mentioned in planning phase 4, core in phase 10, interface in phase 6)
- Legacy .doc/.xls/.ppt controlled converter (the parser has given an explicit error path)
- Semantic recall is turned off by default: when `embedding_model` is empty, there is only FTS5 lexicon. Natural language questions need to be equipped with a small embedding model first.

## Problem record

16. ✅ **QQ image and sticker event parsing (2026-08-30)**: NapCat image/custom-sticker segments may contain
numeric IDs, while the old `dict[str, str]` event model rejected the whole event before parsing. `mface`,
`market_face`, `sticker`, and `emoji` were also absent from the media path, and built-in `face` segments were
silently ignored. The parser now accepts untrusted extension values and normalizes IDs; custom-sticker URLs,
cache paths, base64 payloads, and file tokens reuse the image download and vision path. Built-in faces remain
visible as an explicit `[QQ face]` context marker. Reply-message support is retained.

14. ✅ **QQ file/picture download failed (2026-08-19)**: The download request error inherited the desktop agent and was not followed
NapCat common redirects; now fixed direct connect, follow redirects, streaming limit of 16 MiB, and image MIME awareness by response type.
15. ✅ **Cloud model support (2026-08-19)**: Added OpenAI-compatible Provider. The default is still local Ollama;
After selecting `model_provider: openai`, the API Key is only read from the macOS Keychain account `openai_api_key`.

1. **GitHub push rejected/unstable**: OAuth credentials lack `workflow` scope (mainly blocking), and direct connection
   Intermittent HTTP2 framing errors/timeouts. Local commits and tags are intact.
   Fix: `gh auth refresh -s workflow && git push -u origin main`; retry on network error.
2. **Hermes task-level verification is blocked**: Hermes is not logged in to any model Provider (`hermes status` full ✗).
   The user is required to execute `hermes model` / `hermes auth` and log in to run the task link contract smoke test.
3. **cua-driver TCC pending authorization**: `hermes computer-use doctor` display accessibility and screen recording are not granted;
   The user needs to set authorization in the system or run `hermes computer-use permissions grant`.
4. ✅ **NapCat / QQ (resolved on 2026-08-15)**: The root cause of the installer "not installed" is App Management
   Unauthorized TCC causes root `cp` to be rejected; entry injection is successful after user authorization. QQ account has scanned the QR code to log in.
   The NapCat HTTP client (reported 8765) and HTTP server (3000 sent) have been configured.
   The WhiteNight owner whitelist has been written into the local configuration, and the real QQ sending and receiving closed-loop test passed.
5. **Real file.delete / screen.capture has not been tested at the system level**: Finder automation and screen recording are required respectively.
   Permissions; unit/integration tests have state machines and audits covered with controlled fakes.
6. **DuckDuckGo HTML endpoint 202 anti-crawl**: It has been solved and tested using DDG Lite + Bing, but the upstream may continue
   Changes and upgrades require running `tests/test_web_tools.py` and real search smoke testing.
7. **OCR optional dependency is not included in check.sh**: `ocrmac` depends on pyobjc (macOS only), CI is not installed; local verification
   `uv sync --extra ocr` is required, otherwise the OCR test will be automatically skipped.
8. **SQLite timestamp naive/aware mixed use**: Has been repaired (approval/attenuation) with unified naive-UTC comparison, and will be added later
   Time comparisons must reuse the same convention to prevent `TypeError`.
9. **Hermes submit contract is not locked**: Gateway authentication is passed but the Provider is not logged in; the Adapter is not logged in
   Fail fast (tested `DelegateUnavailableError`). After logging in, the user needs to complete the real task link contract test.
   Then solidify the submit endpoint payload.
10. **Codex real task is not running**: MCP handshake/tool list passed the actual test; to avoid consuming cloud quota, the coding task
Use Fake Provider for state machine testing. Real short task smoke testing (such as generating a hello.py) is left to be executed after user confirmation.
11. **WebUI has not made a visual return to the real browser**: Passed tsc/eslint/build, Vite agent full link and API workflow
Verification; Narrow window/keyboard/accessibility requires the user to open `npm run dev` on the local machine for manual confirmation.
12. ✅ **Ollama was generated out of control resulting in no reply on QQ (fixed on 2026-08-15)**: "Ignore people" twice
The common root cause is not memory/Ollama suspended animation, but the model degradation cycle: WhiteNight tune `/api/chat` not passed
`num_predict`, Ollama continues writing indefinitely under context-shift (log measurement `n_decoded > 4000`),
Occupying a single inference slot, all subsequent messages are queued; `Stopping...` of `ollama ps` is just keep_alive
Misleading display of expiration. Fix: `OllamaProvider` defaults to `max_output_tokens=2048` and writes
`options.num_predict` (`src/whitenight/config.py` can be configured with `model_max_output_tokens`),
Added `tests/test_ollama_contract.py` to lock payload; 136 passed / 4 skipped, real QQ
Closed-loop self-test passed. Actual memory measurement: 16GB is 27% free and 2.4GB is used for swap, which is stressful but not the root cause.
Remaining monitoring gap: 72h inspection only tests `/healthz`, and still cannot distinguish between "can say words but cannot stop"; it can be added later
Really generate smoke test at low frequency (to be confirmed by user).
13. ✅ **Git mistakenly submitted local configuration backup (processed on 2026-08-15)**: `git add -A` mistakenly submitted
`config/whitenight.bak-*` (including owner QQ number) was submitted to `3f44227`; has been moved to the trash,
Added in `.gitignore` and removed in `ae4b6e4`. The warehouse is private; if you want to completely clear it from history, you need to
Rewrite history after confirmation. For subsequent submissions, only use `git add <specific file>` instead of `git add -A`.

## Next step (closing list)

1. ✅ The 72-hour run has been started by the Agent (`run_72h.py`, in progress); real sleep wake-up and network interruption tests can be carried out by the user at his/her choice.
2. The user opens WebUI on the development machine to do visual regression and narrow window confirmation (headless screenshots have been generated).
3. ✅ NapCat installation, QQ code scanning, and real QQ sending and receiving links have been completed (2026-08-15).
4. The user logs in to Hermes Provider and runs the real task link contract test.
5. The user confirms the GPU rental plan, completes LoRA training and blind testing and selects the default model.
6. ✅ GitHub push completed (`gh` credentials + `git push origin main` are normal).

## Verification command

```bash
./scripts/check.sh # ruff + pytest + front-end lint/build
uv run mypy src/whitenight # Strict type checking
WHITENIGHT_TEST_OLLAMA=1 uv run pytest tests/test_ollama_provider.py -q
uv run alembic upgrade head # Database migration
uv run scripts/verify_phase1.py --smoke-model --smoke-gateway
```
## 2026-09-02 maintenance

- Hermes delegation is now opt-in (`hermes_enabled: false` by default); disabled deployments do not
  start or register the Hermes gateway and route GUI requests to WhiteNight locally.
- Codex delegation now requires a leading `/codex` command; the prefix is removed before task
  submission, while ordinary coding requests remain local.
- Removed the WebUI constraints editor and its SOUL/AGENTS file API. Character and persona edits
  remain on the Characters page; `AGENTS.md` remains local engineering metadata.
