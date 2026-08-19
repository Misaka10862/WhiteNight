# NapCat + QQ configuration steps

> Status: ✅ Completed (2026-08-15). The QQ account has been scanned to log in, and OneBot reporting and sending are configured and passed the actual test.
> The WebUI login token is only in the NapCat local configuration file and is not written to the warehouse/log.

## Installation (completed)

1. Open `/Applications/NapCatInstaller.app` (this session is already started).
2. Select "Automatic detection" for the agent and click "Install"; if the system prompts App management, grant permissions.
3. After the installation is complete, follow the prompts "Modify QQ" → "Start NapCat".
4. Use your QQ account to scan the code to log in; do not use your main account (to reduce the impact of risk control).

Note: The installer shows success but the refresh shows "Not Installed". The root cause is that the App Management TCC is not authorized.
Root `cp` was rejected; just try again after authorization in "System Settings → Privacy and Security → App Management".

## NapCat network configuration (completed)

HTTP client (QQ event → WhiteNight):

- Address: `http://127.0.0.1:8765/api/v1/onebot/events`
- Message format: CQ code/array; report `message.private` (group chat is ignored by WhiteNight).

HTTP server (WhiteNight → QQ sent):

- Listening: `127.0.0.1:3000` (consistent with `qq_onebot_api_url`)
- Message format: array; only local access, token is left blank.

WebUI: `http://127.0.0.1:6099/webui` (for the login token, see the NapCat local configuration file).

## WhiteNight side configuration

```bash
uv run scripts/configure_qq.py --owner <QQ trumpet>
# Or manually edit config/whitenight.yaml:
#   qq_enabled: true
# qq_owner_ids: [<QQ trumpet>]
#   qq_onebot_api_url: http://127.0.0.1:3000
```

Restart: `uv run whitenight`. Verify:

```bash
uv run scripts/qq_link_check.py
curl http://127.0.0.1:8765/api/v1/onebot/status
# Expectation: enabled=true, owner_ids=[<QQ trumpet>], QQ LINK READY
```

Sending proactive messages to QQ: Change `proactive_sender` to `qq` (the sending target is owner_ids first).

## Actual measurement record (2026-08-15)

- `scripts/qq_link_check.py` → `QQ LINK READY` (OneBot 3000 reachable + WhiteNight health + owner match).
- Direct sending test: OneBotSender → `send_private_msg`, real QQ received.
- Closed loop test: simulate owner private chat event POST to `/api/v1/onebot/events`,
  Via Adapter → Session → qwen3:8b → Reply back, real QQ received, `get_friend_msg_history` reviewed and delivered.

## Risks and Constraints

- Only the QQ number in owner_ids can trigger tools and approval; group chat is ignored.
- Approval command: `Agree <number>` / `Reject <number>`.
- NapCat version upgrade requires re-running the contract test (`tests/test_onebot.py`).
