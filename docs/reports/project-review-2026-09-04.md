# Architecture review and implementation evidence — 2026-09-04

## Baseline and diagnosis

The reviewed workspace included the pending QQ attachment and native-sticker changes.
Baseline: 241 Python tests passed, 4 optional live integrations skipped. Ruff,
formatting, strict mypy, web lint/build and tracked-secret checks passed.

Synthetic fault injection demonstrated a reversed database restore rollback that
overwrites the safety copy. SQLCipher backup was rejected and migration protection
skipped encrypted databases. Other deterministic defects included mismatched approval
scope, missing browser-origin rejection, provider-error credential reflection,
delegate cancellation/retry state errors, blocking I/O, lexical-only semantic
candidates, rolling-summary coverage loss and stale attachment state.

Model-generated dependent tool calls and repeated calls can trigger failures, but
the missing deterministic scheduling and state checks are program defects. Model
capability evaluation remains separate from these regression tests.

## Implemented stages A–E

- Storage maintenance now validates SQLite/SQLCipher snapshots, coordinates service and
  migration lifetimes with locks, retains old generations, and recovers interrupted restores.
  Commit-journal uncertainty never starts a competing rollback. Backups include all four
  managed asset roots; new attachment receipts use portable relative storage paths.
- HTTP/WS origin boundaries, safe provider errors and metadata-only exception logging close
  the reproduced disclosure paths. Approval selection is explicit and consumption is bound
  to tool, arguments, identity and expiry with atomic replay protection.
- Application composition, model configuration, conversation state, file tasks, tool
  continuation and memory maintenance are separate modules. Existing chat fields coexist
  with correlated versioned event headers. New migrations are 0011 and 0012, both reversible.
- Tool side effects preserve order, pending approvals stop dependent work, and cancellation
  waits for synchronous work to finish. Delegate uncertainty is durable; unverified writes
  are refused. Finished/cancelled requests cannot be overwritten by late lifecycle events.
- Independent lexical/semantic recall, model/content-versioned vectors, incremental summaries
  and per-session durable maintenance replace window-only processing. Proactive delivery
  rechecks current eligibility after generation and before each send attempt.
- WebUI streams survive navigation, requests can be cancelled, file receipts remain visible,
  and backup creation/verification/preview/download are available. Naive database timestamps
  are interpreted as UTC. Backup previews show user-facing counts instead of internal tables.
- Runtime model keys use versioned Keychain accounts, so a failed config replacement cannot
  pair a new key with an old endpoint. Provider instances retain their in-memory generation.
  Keep-alive/tokenizer changes publish only after successful non-secret configuration writes.

## Final automated verification

`./scripts/check.sh` passed: **332 Python tests passed, 4 optional integrations skipped**;
**13 frontend behavior tests passed**; Ruff, formatting, strict mypy over 113 source modules,
TypeScript/Vite, tracked-secret scanning and the technical-English audit passed.
An additional clean-cache strict mypy run passed. Optional OCR imports are explicitly scoped
in mypy configuration so the gate works whether that extra is installed or absent.

The four skips are the live Codex MCP handshake, two local Ollama checks, and optional Apple
Vision OCR. SQLCipher tests ran and passed. No runtime dependency was added or upgraded.
Existing third-party deprecation warnings are retained as diagnostics, not hidden by broad filters.

## Real browser acceptance

The Codex in-app browser tested `scripts/browser_fixture.py` on API 8769/WebUI 5179 using
synthetic messages, an isolated database, in-memory credentials and deterministic inference.
The production service, database, channels and credential store were not used.

| Scenario | Observed result |
|---|---|
| Send in A and switch to B during generation | B stayed empty; returning to A showed its completed reply |
| Navigate to Tasks and back | The request remained owned by A; persisted history was recovered |
| Click Stop immediately after Send | Cancellation was acknowledged and the composer became available |
| Allow once, then allow this session | Once created zero grants; the explicit session choice created one grant |
| Upload and send a synthetic text file | Receipt persisted; history displayed the filename instead of an empty message |
| Create, verify and preview an encrypted backup | All actions succeeded; preview contained 2 sessions, 7 messages and 1 attachment |
| Synthetic model failure | A bounded error appeared and input/draft recovery remained available |
| Stop the fixture API during streaming | Disconnection and failed history refresh were visible; no message was automatically resent |
| 390×844 narrow layout and 1280×900 desktop | Navigation/composer remained usable; document scroll width equalled the 390-pixel viewport |

IME composition, malformed/late events, upload wire format and cancellation races also have
deterministic controller/API coverage. The browser test did not exercise an operating-system IME.
Local screenshots are retained under `data/browser-acceptance-2026-09-04/` (excluded from Git).
The fixture processes and temporary browser tab were stopped after acceptance; test data was retained.

## Remaining scope and delivery

Production sleep/wake, a complete 72-hour report, real outbound QQ/Codex/Hermes tasks and a
production-data restore drill remain separate operational acceptance. LoRA and hosted Actions
remain paused/disabled. Codex writes and unverified Hermes actions remain unavailable.

Session search/archive, retention review lists, incremental backups and legacy Office conversion
remain next-stage work. The pending QQ/sticker baseline is preserved; the unrelated pre-existing
SOUL.md edit is not part of this delivery. Delivery uses one English commit followed by remote
revision verification; Git history records its final identifier.
