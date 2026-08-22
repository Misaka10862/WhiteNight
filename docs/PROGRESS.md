# WhiteNight build progress (procedural documentation)

> This file is updated with each build: recording completed, incomplete, issues and next steps.
> Build outline: `buildplan.md`. Phase conclusions and measured evidence can be found in `docs/reports/`.

Last update: 2026-08-22 (Enabled parallel tool calls and confirmation-free trusted QQ file delivery)

## Current stage

- **File tool loop repair (this round)**: provider-native tool calls from the same model turn now run
  concurrently, with validated results returned in original call order. Trusted OneBot file delivery
  no longer asks for a second confirmation; the server still binds the recipient and verifies the
  canonical path, regular-file status, size limit and SHA-256 immediately before upload. Other
  state-changing file operations keep their existing approval levels. The immutable system safety
  appendix now also requires file intents and short follow-ups such as "send it" to complete through
  real tool results, and forbids claiming success or future execution in place of a tool call.

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
  `get_friend_msg_history` Review delivery. `proactive_sender: qq` Optional (default is still log).
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
- Workbench navigation: Chat/Session/Memory/Task/Approval/Permissions/Model/Constraints/Active/Log/Backup
- Chat page: conversation list, streaming bubbles, pictures, delegated task event bubbles; conversation page: rename/export/delete
- Memory page: retrieval, fact addition, modification and deletion, conflict retention/discard, episodic memory, JSONL/Markdown export
- Task page: Performer/Status/Risk/Product/Error/Abort; Approval page: Risk/Parameter Summary/Allow/Deny
- Permission page: Tool risk rules + session authorization revocation; Model page: DB/Model/Hermes/Codex Health
- Constraint page: SOUL.md / AGENTS.md View and edit (server-side safe writing)
- Active message/log/backup page: honest occupancy (capabilities are accessed in stages 7/10 respectively, no false switches are made)
- Backend supporting API: session rename/delete/export, approvals approve/reject, policy rules/grants,
  system health, rules read and write; 102 passed / 4 skipped
- Narrow window responsive layout + keyboard Enter to send + navigation/aria tag
- Actual test: full link of session/memory/task/approval/permission/model/rules under Vite agent + real Ollama streaming chat passed
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
- The code has switched to the default `model_name=qwen3:8b`, `model_supports_vision=false`;
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
