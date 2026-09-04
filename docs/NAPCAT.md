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
- Images are accepted from the structured OneBot URL/base64/cache-path/file-id
  forms and from legacy CQ-code strings.  NapCat custom stickers (`mface`,
  `market_face`, `sticker`, or `emoji`) use the same media path; built-in
  `face` segments are preserved as explicit context when no bitmap is exposed.
  Reply messages are resolved through
  OneBot `get_msg` when available; the quoted body is bounded and marked as
  untrusted context before it reaches the model.
- NapCat version upgrade requires re-running the contract test (`tests/test_onebot.py`).

## Emotion stickers

Import a transparent 3x3 sheet (existing files are never overwritten):

```bash
uv run scripts/import_stickers.py /absolute/path/sticker-sheet.png
```

The generated PNGs and `catalog.json` live in `data/stickers/`. The PNGs are only source/reference
assets. Personal QQ custom faces are sent through NapCat as an `image` segment with
`sub_type: 1` and the URL returned by `fetch_custom_face_detail`; NapCat renders that segment as
the QQ animated-face marker, not a regular image. Marketplace faces still use the `mface` segment with `emoji_id` and
`emoji_package_id`/`key`. Records without native metadata are disabled for sending rather than
downgraded to an image. Edit `label`, `use_when`, `avoid_when`, and `enabled` directly, then
restart WhiteNight.
The model sees only text hints and does not invoke image understanding to choose a sticker. At most
one native sticker is sent per turn, after the text.

Binding workflow (personal custom faces):

1. Add each PNG to the QQ custom-emoji collection manually.
2. Send each registered emoji once in a group visible to the NapCat account.
3. Run `uv run scripts/sync_qq_stickers.py`. It reads the account's saved-face list, matches the
   QQ remarks to local `sticker-*.png` files, and writes native delivery URLs into the catalog.
4. Restart WhiteNight and confirm the OneBot status reports 18 native stickers.

Example native binding:

```json
{
  "id": "sticker-01",
  "file": "sticker-01.png",
  "label": "happy playful",
  "use_when": ["happy", "playful"],
  "avoid_when": ["serious"],
  "enabled": true,
  "segment_type": "image",
  "sub_type": 1,
  "native_url": "https://p.qpic.cn/qq_expression/<uin>/<res-id>/0"
}
```
