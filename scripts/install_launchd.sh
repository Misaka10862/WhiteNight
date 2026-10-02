#!/usr/bin/env bash
# Default is a side-effect-free preview. Installation preserves a rollback plist.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
SERVICE_APP="${WHITENIGHT_APP_PATH:-$HOME/Applications/WhiteNight.app}"
LABEL="com.whitenight.service"
AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/WhiteNight"
PLIST_TARGET="$AGENTS_DIR/$LABEL.plist"
DOMAIN="gui/$(id -u)"

generate() {
  .venv/bin/python - "$SERVICE_APP" "$PROJECT_DIR" "$LOG_DIR" <<'PY'
import os
import plistlib
import sys
app, project, logs = sys.argv[1:]
plist = {
    "Label": "com.whitenight.service",
    "ProgramArguments": [app + "/Contents/MacOS/WhiteNight", "--project", project],
    "WorkingDirectory": project, "RunAtLoad": True, "KeepAlive": True,
    "ProcessType": "Interactive", "ExitTimeOut": 60,
    "StandardOutPath": logs + "/whitenight.out.log",
    "StandardErrorPath": logs + "/whitenight.err.log",
    "EnvironmentVariables": {"PATH": os.path.expanduser("~/.local/bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
}
sys.stdout.buffer.write(plistlib.dumps(plist))
PY
}

bootstrap_job() {
  for ((attempt=0; attempt<10; attempt++)); do
    if launchctl bootstrap "$DOMAIN" "$PLIST_TARGET"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

case "${1:-}" in
  --install)
    ./scripts/build_service_app.sh
    mkdir -p "$AGENTS_DIR" "$LOG_DIR"
    PREVIOUS=""
    if [[ -f "$PLIST_TARGET" ]]; then
      PREVIOUS="$LOG_DIR/$LABEL.$(date +%Y%m%dT%H%M%S).plist.backup"
      cp -p "$PLIST_TARGET" "$PREVIOUS"
      echo "Rollback configuration: $PREVIOUS"
    fi
    # bootout can return before the old job fully leaves its launchd domain.
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      launchctl bootout "$DOMAIN/$LABEL"
      for ((attempt=0; attempt<50; attempt++)); do
        if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
          break
        fi
        sleep 1
      done
      if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
        echo "Previous service is still exiting; no second instance was started." >&2
        exit 1
      fi
    fi
    generate > "$PLIST_TARGET"
    if ! bootstrap_job; then
      if [[ -n "$PREVIOUS" ]]; then
        cp -p "$PREVIOUS" "$PLIST_TARGET"
        bootstrap_job
      fi
      exit 1
    fi
    launchctl enable "$DOMAIN/$LABEL"
    echo "Installed: $SERVICE_APP"
    echo "Grant WhiteNight Full Disk Access in System Settings, then restart this service."
    ;;
  --uninstall)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      launchctl bootout "$DOMAIN/$LABEL"
    fi
    .venv/bin/python - "$PLIST_TARGET" <<'PY'
import shutil
import sys
from pathlib import Path
from uuid import uuid4
path = Path(sys.argv[1])
if path.exists():
    shutil.move(str(path), str(Path.home() / ".Trash" / (uuid4().hex + "-" + path.name)))
PY
    ;;
  *) generate ;;
esac
