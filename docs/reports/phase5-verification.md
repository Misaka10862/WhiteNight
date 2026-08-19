# Phase 5 routing and agent delegation actual test report (2026-08-15)

>Rerun: `uv run pytest` (97 passed, 4 skipped)
> Phase 5 exit conditions: The golden routing set reaches the target accuracy; Hermes/Codex failure does not destroy the main session and can be safely retried.

## 1. Routing

- `RuleRouter`: Rule priority, high precision. Sequence: User specified → Image Q&A → Encoding rules →
  GUI/Cross-Application → Memory → Search → File Operations → Default Local Companion.
- `RoutingEngine`: rules → optional `OllamaRoutingRouter` (strict JSON) → local cover;
  Explicit `user_override` is obeyed within permissions.
- Golden set `evals/routing/golden.jsonl` (16 examples):
  companionship/image_qa/memory/search/file_op/gui/code/user-override full coverage,
  **Accuracy ≥ 0.9 meets the standard** (test assertion).

## 2. Delegation protocol and adapter

- `DelegateEvent` standard envelope: queued/started/progress/approval_required/artifact/
  result/error/aborted; `DelegateProvider` protocol unifies Hermes and Codex.
- **Codex MCP Adapter (passed the actual test)**:
  - stdio JSON-RPC client (initialize → tools/list → tools/call);
  - `codex` (new session, cwd/sandbox=workspace-write/approval-policy=on-request)
with `codex-reply`(threadId continued);
  - Real handshake test `WHITENIGHT_TEST_CODEX_MCP=1` → 2 passed, the tool list is
    `codex` + `codex-reply`；
  - Timeout/process exit turns into `DelegateError`, safe to retry.
- **Hermes Gateway Adapter (passed the actual test)**:
  - `/api/status` health check successful (v0.17.0);
  - `/api/auth/me` 401/403 → `DelegateUnavailableError` (measured trigger),
The submit contract is locked after the user logs into the Provider to avoid side effects from guessing the protocol.

## 3. Task management

- Migrate `0005 agent_tasks`: executor/category/status/risk/thread_id/product/error/attempts.
- `DelegateManager`: run/retry (limited retry on failure and generate progress event)/abort/
  Unavailable. Fail fast; final state is persistent.
- Task API: `GET /api/v1/tasks`, `GET /api/v1/tasks/{id}`,
  `POST /api/v1/tasks/{id}/abort`。
- ChatService integration: transparently transmit `type:"task"` events when routing to Codex/Hermes;
  As a result, the original text was saved and a line of personalized explanation was added (the technical content was not modified);
  **Normal chat in the same session will continue to be available after delegation fails (integration test)**.

## 4. Failure and recovery verification

- Fake Codex successful: task `succeeded` and thread_id persisted.
- Flaky Provider: 1st failure → 2nd success, `attempts=2`.
- Unavailable: Fast failure is an error event, and the main session can still chat locally.
- Aborted: task status → `aborted`.

## 5. Boundaries (documented in PROGRESS)

- The Hermes submit endpoint contract requires users to log in to the Provider and perform actual task testing.
- Codex real encoding tasks are not running (to avoid consuming quota), and the MCP handshake has been measured.
- Progress event: A single call to Codex MCP does not provide streaming content, currently only started/result;
  Hermes contracts should provide real progress once locked. Don’t fake steps that didn’t happen.
