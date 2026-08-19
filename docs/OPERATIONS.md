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
| Hermes task fails immediately | `hermes status` Whether to log in to the Provider; not logged in is expected to fail quickly |
| QQ not responding | First check whether there is a "Model call failed" reply in QQ; then check whether the Ollama log `n_decoded` continues to grow without `done` (out-of-control generation); backend/NapCat status and owner whitelist |
| QQ reply is slow (it takes more than ten seconds to reply) | Usually it is a cold start: `ollama ps` cannot see the model or `UNTIL` is approaching; WebUI "Model and Agent" can switch the resident policy (default `-1` is resident) |
| It took a long time for QQ to reply | First check whether the Mac is sleeping (the local service does not run during sleep); if necessary, run `scripts/keep_awake.sh start` after being connected to the power supply online for 24 hours; then see if `ollama ps` has a model cold start |
| Memory retrieval occupies the reasoning slot | The length has been limited to 512 tokens and the chat will be canceled first; if it is still abnormal, check the log `Ollama /api/chat` long task |
| Ollama is generated out of control (`/api/chat` does not return for a long time, and the log `n_decoded` continues to grow) | The code has forced `num_predict` (default 2048); emergency can `brew services restart ollama` or kill the `llama-server` process |
| Proactive message not sent | Sender is log before phase 8; confirm `proactive_enabled` and silent period |

## Security reminder

- Never commit `.env`, `WHITENIGHT_BACKUP_KEY`, Keychain content to Git.
- Permission rules cannot be modified by commands from external web pages/documents/chat; rules can only be modified through the WebUI constraint page.
- Deleting single files goes into the trash; batch deletions will not be performed by the Agent.
