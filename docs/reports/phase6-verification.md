# Phase 6 complete WebUI test report (2026-08-15)

>Rerun: `./scripts/check.sh` (ALL CHECKS PASSED); `uv run pytest` (102 passed, 4 skipped)

## 1. Workbench page

| Page | Capabilities |
|---|---|
| Chat | Conversation list, streaming replies, image upload, delegated task event bubbles |
| Session | Rename, export Markdown/JSONL, delete (immediate removal + no text audit) |
| Memory | Mixed retrieval, fact addition, deletion, conflict retention/discard, episodic memory addition, deletion, export |
| Task | Performer/Status/Risk/Number of Attempts/Thread/Product/Error + Abort |
| Approval | Risk/Scope/Parameter Summary + Allow Once/Allow This Session/Deny |
| Permissions | Tool Risk Rules Table + Session Authorization Revocation |
| Model | Database/Model/Hermes/Codex Health Status |
| Active/log/backup | Honest occupancy, capabilities are accessed in stage 7/10, no false switches |

## 2. Supporting backend API (new in phase 6)

- `PATCH/DELETE /api/v1/sessions/{id}`、`GET .../export?fmt=`
- `GET /api/v1/approvals/pending`、`POST .../{code}/approve|reject`
- `GET /api/v1/policy/rules`、`GET/DELETE /api/v1/policy/grants[/{id}]`
- `GET /api/v1/system/health` (DB + model + Codex/Hermes health)

## 3. Usability and Accessibility

- Narrow window: Navigation collapses into a hamburger button, and session columns/columns become single columns (CSS @media).
- Keyboard: Chat Enter to send, Shift+Enter to wrap; form native submission.
- aria-label covers main navigation, chat input, image selection, and each page section;
  Task/approval status is marked with text and errors with role="alert".

## 4. Actual measurement

- Front-end: eslint ✓, tsc ✓, vite build ✓ (85 modules).
- Vite agent full link: create/rename/export/delete sessions, fact addition, deletion and retrieval,
  Task/Approval/Permission/Model pages, all passed.
- Real Ollama streaming chat via Vite WebSocket proxy: `Reply only two words: In' → "In".
- Backend 102 tests: including session deletion audit, approval non-replayable, session authorization revocation,
  The system is healthy.

## 5. Boundary

- Real browser visual regression requires user manual confirmation (tsc/build/API has been covered).
- Active messages, logs and backup pages are placeholders; the corresponding backend will be delivered in Phase 7/10.
