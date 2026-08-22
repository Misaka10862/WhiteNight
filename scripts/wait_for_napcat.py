#!/usr/bin/env python3
"""Wait for NapCat and notify the user without changing configuration.

Usage:
    uv run scripts/wait_for_napcat.py --timeout 86400
Sends a macOS notification after detecting the NapCat WebUI or OneBot endpoint
and writes the event to data/logs/napcat-ready.jsonl.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=24 * 3600)
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()

    deadline = time.time() + args.timeout
    log_path = ROOT / "data" / "logs" / "napcat-ready.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    while time.time() < deadline:
        webui = False
        onebot = False
        try:
            response = httpx.get("http://127.0.0.1:6099/", timeout=2.0, trust_env=False)
            webui = response.status_code < 500
        except Exception:
            pass
        try:
            response = httpx.get(
                "http://127.0.0.1:3000/get_login_info", timeout=2.0, trust_env=False
            )
            onebot = response.status_code == 200
        except Exception:
            pass
        if webui or onebot:
            record = {
                "ts": datetime.now(UTC).isoformat(),
                "webui": webui,
                "onebot": onebot,
            }
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'display notification "NapCat is ready; scan the QR code to sign in" '
                    'with title "WhiteNight"',
                ],
                check=False,
            )
            print("NAPCAT READY - scan the QR code to sign in", flush=True)
            return 0
        time.sleep(args.interval)

    print("Timed out waiting for NapCat", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
