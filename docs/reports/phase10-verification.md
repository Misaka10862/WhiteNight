# Phase 10 release reinforcement actual test report (2026-08-15)

>Rerun: `uv run pytest` (125 passed, 4 skipped); `./scripts/check.sh` passed.

## 1. Encrypted backup and recovery

- Format: `WNBK1 | salt(16B) | Fernet(token(tar.gz))`; PBKDF2-SHA256 600k derived key.
- Content: SQLite online backup (can also be backed up while the service is running) + `data/attachments`.
- CLI：`generate-key / backup / verify / preview / restore`；
To restore the key, use `WHITENIGHT_BACKUP_KEY` or `--passphrase`.
- Recovery protection: `/healthz` is rejected when alive; the current library is renamed for safe backup; failure automatically rolls back.
- **Actual Measurement**:
  - Temporary library: backup → verify/preview (sessions=1, messages=1) → restore and replace,
Before recovery, new data is discarded and old data is returned intact.
  - Bad key rejected (decryption failed).
  - The real encrypted backup of the dev database is 9869 bytes, verify/preview passed.

## 2. Diagnosis and logs

- `scripts/diagnostics.py --json`: DB integrity/migrations/disk/attachments/
  The number of approvals pending/Ollama/Codex/Hermes/ at the end of the log, the actual measurement is all green.
- The log is saved to `data/logs/whitenight.log` (writes the desensitization filter).
- `/api/v1/logs?lines=N` + WebUI log page (5s refresh).

## 3. Stability tools

- `scripts/load_smoke.sh`: 30 rounds of session creation/list/status/deletion smoke.
- `scripts/run_72h.py --hours 72`: health check every minute, exception count and JSONL logging.

## 4. Documentation

- `docs/INSTALL.md`: installation, first startup, system permissions, QQ configuration, backup key.
- `docs/OPERATIONS.md`: health check, migration rollback, backup and recovery, common faults.
- `docs/RELEASE_CHECKLIST.md`: Section 18 of the construction plan is checked item by item.

## 5. To be executed by the user (cannot be automated)

- 72 hours of continuous operation + actual test of sleep wake-up/network interruption.
- Real browser visual return; NapCat QQ login and real link; Hermes Provider login.
- LoRA training/blind testing selects the default model; GitHub push (workflow scope).

## 6. Security Red Teaming and Performance (Round 12 Supplement)

- `evals/security/golden.jsonl` 8 items; new prompt injection no change rules, SSRF loopback/private network
  The request is rejected before the Provider; original batch deletion/approval replay/non-owner/attachment MIME/log desensitization
  All included in the list.
- `tests/test_performance.py`: 100 session messages, 200 message context budget, 200 fact FTS,
  All 100 routes are within the relaxed threshold.
- `scripts/e2e_smoke.py`: Both dummy and real-ollama modes pass (session/streaming chat/
  memory/active messaging/encrypted backup).
- Final `uv run pytest`: 132 passed, 4 skipped.
