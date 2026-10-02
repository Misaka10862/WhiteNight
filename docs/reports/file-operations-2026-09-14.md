# File-operation incident and repair

## Attribution

The September 14 15:52–15:57 CST conversation, pending calls and audit rows show
five approvals for one attachment move; four have identical parameter digests.
The first destination differs only in case, and a filesystem identity check shows
both spellings refer to the same directory. The search tool only inspected files,
so directory queries returned irrelevant files or no matches. Approval commands
without a separating space and the all-approval command entered the model loop
and created further requests. A progress question also re-entered search instead
of reading the existing pending operation.

These are deterministic implementation defects. Repeated fuzzy searches and
incorrect absence claims are model limitations amplified by missing structured
context. The repair adds directory lookup, shared command parsing, bound request
deduplication, atomic claims, persisted receipts and deterministic status answers.

## Dedicated macOS application

Build with `./scripts/build_service_app.sh`; preview the launchd configuration
with `./scripts/install_launchd.sh`; install with `--install`. The fixed default
application is `~/Applications/WhiteNight.app`, bundle ID
`com.whitenight.service-app`. A native AppKit process remains alive while its child
runs `.venv/bin/python -m whitenight`; runtime no longer starts through `uv run`.
The interpreter environment must already be installed. No dependency versions or
third-party libraries were added; the launcher uses the installed macOS SDK.

The build is signed locally with an ad-hoc signature by default, or with
`WHITENIGHT_SIGNING_IDENTITY` when configured. Unchanged builds are reused, so
Python-only updates do not rebuild the responsible application. Native launcher
or signature changes can require renewed macOS consent; this is diagnosed rather
than promising permanent authorization across application changes.

Grant WhiteNight Full Disk Access in System Settings, restart the service, then
use Permissions → local file access → probe. macOS requires the user to grant this
permission; application code cannot grant it. Diagnostics run in the real service
process and do not treat a successful terminal probe as proof of service access.
Neither root privileges nor system-protection changes are used.

The installer preserves the previous plist under `~/Library/Logs/WhiteNight` and
stops the old job before starting the new one. To revert, boot out the current job,
copy the recorded backup to `~/Library/LaunchAgents/com.whitenight.service.plist`,
and bootstrap it again. Never run both services simultaneously. Startup uses the
existing verified pre-migration database backup workflow. Rollback of code before
migration 0013 additionally requires its downgrade while the service is stopped;
revoked legacy duplicate/expired approvals are intentionally not reactivated.

## Validation

Regression coverage reproduces the conversation, case aliases, Chinese names,
spaces, missing destinations, optional spaces in codes, repeated and concurrent
requests, snapshot approval, rejection, cross-session isolation, expiry, file
changes, overwrite conflicts, interrupted execution and audit-based recovery.
File fixtures use temporary directories and fake providers; no real QQ messages
are sent. Runtime deployment and user-granted access results are recorded in
`docs/PROGRESS.md`.
