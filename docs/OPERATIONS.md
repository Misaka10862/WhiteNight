# Operation, maintenance and troubleshooting

## Health Check

```bash
./scripts/check_service.sh
uv run scripts/diagnostics.py --json
curl http://127.0.0.1:8765/api/v1/system/health
```

## Log

- File: `data/logs/whitenight.log` (desensitized when writing)
- WebUI: Workbench → Logs; API: `GET /api/v1/logs?lines=200`

## Database migration and rollback

Stop the WhiteNight service before running a standalone migration or restore. Normal startup takes
an exclusive maintenance lock, recovers an unfinished restore journal, checks the migration backup,
then downgrades to a shared lock for the service lifetime. Direct Alembic upgrade/downgrade commands
use the same lock boundary; a failed HTTP probe is not evidence that the database is unused.
With `auto_migrate=false`, startup refuses an unfinished journal; run the offline `recover` command
before starting the service instead of opening a mixed generation.

```bash
# One-time initialization; retains an existing recovery key.
uv run scripts/backup.py generate-key
uv run scripts/backup.py backup --output data/backups/pre-migrate-unique.bak
uv run scripts/backup.py verify --input data/backups/pre-migrate-unique.bak
# Stop the service, then run the selected operation.
uv run alembic upgrade head
# A schema downgrade is a separate operation, after reviewing its data implications.
uv run alembic downgrade -1
```

Before an existing database changes revision, a `pre-migrate-*.db` safety snapshot is created and
integrity-checked. SQLCipher snapshots remain encrypted with the database key. A failed snapshot
check blocks migration. Keep an authenticated `.bak` archive as the normal recovery artifact.
After upgrading or downgrading, run the checks and an isolated startup smoke test before resuming use.
Do not combine "restore an older archive" and "downgrade the restored schema" without checking its revision.

## Backup and recovery

- Recovery keys live in macOS Keychain under the configured service and account `backup-recovery-key`.
  `generate-key` initializes the account without printing the key; `configure-key` imports an existing
  recovery key through a hidden prompt and refuses to replace an existing account. Neither command
  accepts secrets in command arguments or environment variables.
- The WNBK1 authenticated container remains compatible with earlier SQLite archives. New archives add
  a versioned manifest and include `attachments`, `qq_files`, `characters` and `stickers`.
- A SQLCipher archive uses an encrypted database snapshot keyed independently by the recovery key.
  Restoring requires the recovery key plus the target database key in Keychain; the original database
  master key is not embedded in the archive. SQLite/SQLCipher conversion is a separate migration and
  is rejected by restore. Legacy SQLite archives manage only their original attachment inventory.
- The WebUI can create, verify, preview and download backups. Restoration is deliberately offline:

```bash
uv run scripts/backup.py verify --input data/backups/selected.bak
uv run scripts/backup.py preview --input data/backups/selected.bak
# Stop the service first; restore refuses a conflicting service or maintenance lock.
uv run scripts/backup.py restore --input data/backups/selected.bak
# If a prior restore was interrupted, this command performs journal recovery only.
uv run scripts/backup.py recover
```

Restore verifies the archive before replacement, stages a new generation, journals the operation,
and moves the old database, WAL/SHM and resource roots into retained generation directories. An ordinary
failure rolls back; an interrupted process is recovered before the next normal startup. A corrupt
journal fails closed and requires inspection. No backup/restore operation wipes old resource directories.
The result identifies the retained safety database and generation. Inspect these before any manual cleanup.
SQLCipher scratch snapshots are encrypted, owner-only temporary files retained for inspection.

A periodic production recovery drill still requires an agreed maintenance window. To rehearse without
production data, use disposable settings and test credentials; do not point test commands at the live database.

## Common faults

| Phenomenon | Treatment |
|---|---|
| Ollama 502 | Native agent hijacking; code has trust_env=False, check Clash/system agent vs. Ollama process |
| The picture understanding model says "I didn't see the picture" | The picture must be hung in the message; rerun the phase 1 smoke test after upgrading Ollama |
| Codex task fails immediately | Check installation/authentication without printing credential content. Only explicitly requested new read-only tasks are supported; write delegation and unverified thread resumption are refused. |
| Hermes task is unavailable | Hermes delegation is disabled by default; set `hermes_enabled: true` only after configuring and authenticating the gateway |
| QQ not responding | First check whether there is a "Model call failed" reply in QQ; then check whether the Ollama log `n_decoded` continues to grow without `done` (out-of-control generation); backend/NapCat status and owner whitelist |
| QQ reply is slow (it takes more than ten seconds to reply) | Usually it is a cold start: `ollama ps` cannot see the model or `UNTIL` is approaching; WebUI "Model and Agent" can switch the resident policy (default `-1` is resident) |
| It took a long time for QQ to reply | First check whether the Mac is sleeping (the local service does not run during sleep); if necessary, run `scripts/keep_awake.sh start` after being connected to the power supply online for 24 hours; then see if `ollama ps` has a model cold start |
| Memory retrieval occupies the reasoning slot | The length has been limited to 512 tokens and the chat will be canceled first; if it is still abnormal, check the log `Ollama /api/chat` long task |
| Ollama is generated out of control (`/api/chat` does not return for a long time, and the log `n_decoded` continues to grow) | The code has forced `num_predict` (default 2048); emergency can `brew services restart ollama` or kill the `llama-server` process |
| Proactive message not sent | Open the Active page and check delivery status. QQ mode requires `qq_enabled=true`, a non-empty `qq_owner_ids`, a logged-in OneBot endpoint and `proactive_sender: qq`; failed sends are retried and recorded with metadata only. |
| Cloud chat returns 400 for `tools[0].function.name` | The adapter now translates dotted internal tool names to the OpenAI-compatible `[A-Za-z0-9_-]+` form. Restart the WhiteNight service after upgrading and retry the message. |
| QQ/OneBot is offline | `curl -X POST http://127.0.0.1:3000/get_login_info -d '{}'` and `uv run scripts/qq_link_check.py`; start QQ/NapCat and complete login manually, then confirm `QQ LINK READY`. |

## Sticker catalog

- Runtime assets live in `data/stickers/` and are ignored by Git.
- Import only a transparent 3×3 sheet with `uv run scripts/import_stickers.py`; existing files are never overwritten.
- Run `uv run scripts/sync_qq_stickers.py` after registering/sending the saved faces; edit labels or enable flags in `catalog.json` if needed, then restart WhiteNight. IDs, file paths, and native transport metadata are validated before a model can select them; missing native metadata never falls back to ordinary image sending.
- Sticker delivery is restricted to the configured owner’s QQ private chat, one per turn, with text sent first and a metadata-only audit record. Personal QQ custom faces use NapCat `image/sub_type=1` and render as the QQ animated-face marker; they are never sent as ordinary image segments (`sub_type=0`).

## Model and service controls

- The Dashboard Model page requires exactly one active Provider: local Ollama or an OpenAI-compatible API.
- Use “Fetch” beside the model name to query the selected Provider’s available models; Ollama uses `/api/tags`, while cloud Providers use `/models`. If the list fails, verify Base URL, Ollama availability, or the cloud API Key.
- Cloud API keys are written only to macOS Keychain. The model name and Base URL are persisted in `config/whitenight.yaml`.
- “Restart WhiteNight service” works when the backend is managed by the fixed launchd label `com.whitenight.service`; manually started processes return a clear unsupported response.
- Proactive delivery audit records do not contain message bodies. Ordinary chat messages remain in conversation storage and are not security-audit events.

## Security reminder

- Never commit `.env`, recovery keys, database keys or Keychain content to Git. Recovery credentials must not be placed in shell arguments, environment files or logs.
- Permission rules cannot be modified by commands from external web pages/documents/chat; edit character/persona content from the Characters page. `AGENTS.md` remains a local engineering file.
- Deleting single files goes into the trash; batch deletions will not be performed by the Agent.
