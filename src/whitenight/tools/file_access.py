"""On-demand probes run inside the actual service process, not a terminal helper."""

import os
import sys
from pathlib import Path

from whitenight.tools.paths import path_error

SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"


def file_access_status(*, probe: bool = False) -> dict[str, object]:
    app_path = os.environ.get("WHITENIGHT_SERVICE_APP")
    paths = [Path.home() / name for name in ("Desktop", "Documents", "Downloads")]
    if Path("/Volumes").is_dir():
        paths.extend(Path("/Volumes").iterdir())
    results: list[dict[str, object]] = []
    if probe:
        for path in paths:
            try:
                with os.scandir(path) as entries:
                    next(entries, None)
                results.append(
                    {"path": str(path), "status": "readable", "writable": os.access(path, os.W_OK)}
                )
            except OSError as exc:
                results.append(
                    {
                        "path": str(path),
                        "status": "denied" if isinstance(exc, PermissionError) else "error",
                        "message": path_error(exc),
                    }
                )
    return {
        "application": app_path or str(Path.home() / "Applications/WhiteNight.app"),
        "dedicated_launcher": bool(app_path),
        "pid": os.getpid(),
        "executable": sys.executable,
        "settings_url": SETTINGS_URL,
        "results": results,
        "note": "请为 WhiteNight 授予完全磁盘访问权限后重启服务，再检测。检测仅证明所列目录的读取能力及写权限标志。",
    }
