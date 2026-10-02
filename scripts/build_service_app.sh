#!/usr/bin/env bash
# Build the dedicated background app using system frameworks; no package changes.
set -euo pipefail
cd "$(dirname "$0")/.."
SERVICE_APP="${WHITENIGHT_APP_PATH:-$HOME/Applications/WhiteNight.app}"
SIGNING_IDENTITY="${WHITENIGHT_SIGNING_IDENTITY:--}"
SOURCE="scripts/service_app/WhiteNight.swift"
DIGEST="$(shasum -a 256 "$SOURCE" | cut -d ' ' -f 1):$SIGNING_IDENTITY"
if [[ -x "$SERVICE_APP/Contents/MacOS/WhiteNight" && -f "$SERVICE_APP/Contents/Resources/build-id" ]] && [[ "$(cat "$SERVICE_APP/Contents/Resources/build-id")" == "$DIGEST" ]]; then
  if codesign --verify --strict "$SERVICE_APP"; then
    echo "Reusing: $SERVICE_APP"
    exit 0
  fi
fi
mkdir -p "$SERVICE_APP/Contents/MacOS" "$SERVICE_APP/Contents/Resources"
if [[ -f "$SERVICE_APP/Contents/MacOS/WhiteNight" ]]; then
  BACKUP_DIR="$HOME/Library/Application Support/WhiteNight/launcher-backups/$(date +%Y%m%dT%H%M%S)"
  mkdir -p "$BACKUP_DIR"
  cp -p "$SERVICE_APP/Contents/MacOS/WhiteNight" "$BACKUP_DIR/WhiteNight"
fi
swiftc -O "$SOURCE" -o "$SERVICE_APP/Contents/MacOS/WhiteNight"
.venv/bin/python - "$SERVICE_APP" <<'PY'
import plistlib
import sys
from pathlib import Path
app = Path(sys.argv[1])
with (app / "Contents/Info.plist").open("wb") as handle:
    plistlib.dump({
        "CFBundleIdentifier": "com.whitenight.service-app",
        "CFBundleName": "WhiteNight",
        "CFBundleDisplayName": "WhiteNight",
        "CFBundleExecutable": "WhiteNight",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "LSUIElement": True,
        "NSDesktopFolderUsageDescription": "WhiteNight accesses files at your request.",
        "NSDocumentsFolderUsageDescription": "WhiteNight accesses documents at your request.",
        "NSDownloadsFolderUsageDescription": "WhiteNight accesses downloads at your request.",
    }, handle)
PY
printf '%s\n' "$DIGEST" > "$SERVICE_APP/Contents/Resources/build-id"
codesign --force --sign "$SIGNING_IDENTITY" --identifier com.whitenight.service-app "$SERVICE_APP"
codesign --verify --strict "$SERVICE_APP"
echo "Built: $SERVICE_APP"
