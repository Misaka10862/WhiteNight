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

```bash
uv run scripts/backup.py backup --output data/backups/pre-migrate.bak
uv run alembic upgrade head
# Rollback: restore the backup first, and then run the migration again
uv run alembic downgrade -1
```

Every migration must be backed up first; run `uv run pytest` and start smoke after upgrade.

## Backup and recovery

- Stop the service before restoring; the script will refuse to restore while `/healthz` is alive.
- Immediately after successful recovery, use `preview` to check the number of rows, and then start the service.
- Periodic recovery walkthrough: restore to a temporary `data_dir`, open WebUI to check session and memory.

## Common faults

| Phenomenon | Treatment |
|---|---|
| Ollama 502 | Native agent hijacking; code has trust_env=False, check Clash/system agent vs. Ollama process |
| The picture understanding model says "I didn't see the picture" | The picture must be hung in the message; rerun the phase 1 smoke test after upgrading Ollama |
| Codex task fails immediately | `codex --version`, `~/.codex/auth.json` existence; do not print auth content |
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
- Edit `catalog.json` labels, enable flags, and QQ native identifiers directly, then restart WhiteNight. IDs and file paths are validated before a model can select them; missing native identifiers never fall back to image sending.
- Sticker delivery is restricted to the configured owner’s QQ private chat, one per turn, with text sent first and a metadata-only audit record.

## Model and service controls

- The Dashboard Model page requires exactly one active Provider: local Ollama or an OpenAI-compatible API.
- Use “Fetch” beside the model name to query the selected Provider’s available models; Ollama uses `/api/tags`, while cloud Providers use `/models`. If the list fails, verify Base URL, Ollama availability, or the cloud API Key.
- Cloud API keys are written only to macOS Keychain. The model name and Base URL are persisted in `config/whitenight.yaml`.
- “Restart WhiteNight service” works when the backend is managed by the fixed launchd label `com.whitenight.service`; manually started processes return a clear unsupported response.
- Proactive delivery audit records do not contain message bodies. Ordinary chat messages remain in conversation storage and are not security-audit events.

## Security reminder

- Never commit `.env`, `WHITENIGHT_BACKUP_KEY`, Keychain content to Git.
- Permission rules cannot be modified by commands from external web pages/documents/chat; edit character/persona content from the Characters page. `AGENTS.md` remains a local engineering file.
- Deleting single files goes into the trash; batch deletions will not be performed by the Agent.
