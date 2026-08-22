#!/usr/bin/env python3
"""Configure QQ / OneBot for stage 8, backing up before writing.

Usage:
    uv run scripts/configure_qq.py --owner 10001
    uv run scripts/configure_qq.py --owner 10001 --owner 10002 \
        --api-url http://127.0.0.1:3000 --no-enable
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path("config/whitenight.yaml")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, action="append", type=int)
    parser.add_argument("--api-url", default="http://127.0.0.1:3000")
    parser.add_argument("--enable", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    path = args.config
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            print(f"Configuration root is not a mapping: {path}", file=sys.stderr)
            return 1
        data = loaded

    if path.exists():
        backup = path.with_suffix(f".bak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
        shutil.copy2(path, backup)
        print(f"Backup created: {backup}")

    data["qq_enabled"] = args.enable
    data["qq_owner_ids"] = args.owner
    data["qq_onebot_api_url"] = args.api_url
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=True), encoding="utf-8")
    print(f"Updated: {path}")
    print(f"  qq_enabled={data['qq_enabled']}")
    print(f"  qq_owner_ids={data['qq_owner_ids']}")
    print(f"  qq_onebot_api_url={data['qq_onebot_api_url']}")
    print("Restart WhiteNight, then configure the NapCat WebUI HTTP event target:")
    print("  http://127.0.0.1:8765/api/v1/onebot/events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
