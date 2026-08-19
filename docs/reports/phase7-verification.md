# Phase 7 Background Service and Active Behavior Measurement Report (2026-08-15)

>Rerun: `uv run pytest` (110 passed, 4 skipped); `./scripts/check.sh` passed.

## 1. Poisson scheduling

- Exponential interval: `-ln(1-u)/rate`, rate = daily expected times / active minutes.
- Silent period: Candidates falling in the silent interval will automatically jump to continue sampling after the silence ends (all 200 random verifications avoid 23:00–08:00).
- Last activity suppression: Candidates no older than `last_activity + suppress_minutes`.
- No reissue after expiration: Now it is later than the candidate and exceeds the grace period (default 45 minutes, simulates sleep/disconnection) → rescheduling, no centralized reissue.
- Pause: `paused` + `paused_until` persistence; automatic recovery at the point.

## 2. Active message service

- `ProactiveService.tick`: five path deterministic outputs of shutdown/pause/unexpired/expired/expired.
- Message combination: SOUL.md + long-term memory recall (preference/salutation/memorial) → local model generates 2-3 sentences of text.
- Sender protocol: Phase 7 defaults to `LogSender` (`data/logs/proactive.jsonl`), and phase 8 changes to QQ OneBot.
- Limited retry on failure (2 times, exponential backoff), rescheduling after failure without reissue.
- The background loop starts with the API lifespan, 30s tick; closing the WebUI does not affect the service.

## 3. Activity access and API

- ChatService logs `last_activity_at` after each user message is dropped.
- `/api/v1/proactive/status|config|pause|resume`; the WebUI active message page is the real configuration page.

## 4. launchd and menu bar

- `deploy/com.whitenight.service.plist.template`: RunAtLoad + KeepAlive + log path + PATH.
- `scripts/install_launchd.sh`: The default is dry-run, `--install/--uninstall` is used to modify the system.
- `scripts/check_service.sh`: health check (actually measured healthy).
- Menu bar entry: `scripts/menu_bar/MenuBarStatus.swift` has been compiled to arm64 Mach-O with swiftc
  Verification passed (status + open WebUI + exit).

## 5. Actual measurement and boundaries

- Real service API: status/config/pause/resume all returns the correct status and candidate time.
- The service still runs after closing the WebUI: the background loop is within the API process and is not coupled to the WebUI.
- Real QQ sender phase 8 access; the current active message is written to the local log and no false sending is performed.
