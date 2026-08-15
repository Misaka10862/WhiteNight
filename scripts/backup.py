#!/usr/bin/env python3
"""WhiteNight 加密备份/恢复 CLI（阶段 10）。

恢复密钥通过环境变量 WHITENIGHT_BACKUP_KEY 提供；也可 --passphrase。
生成独立恢复密钥：
    uv run scripts/backup.py generate-key   # 打印后请离线保存
备份（服务运行中也可以，SQLite online backup）：
    uv run scripts/backup.py backup --output data/backups/whitenight.bak
验证/预览/恢复（恢复前请停止服务）：
    uv run scripts/backup.py verify --input <bak>
    uv run scripts/backup.py preview --input <bak>
    uv run scripts/backup.py restore --input <bak>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from whitenight.config import load_settings
from whitenight.storage.backup import (
    create_backup,
    generate_recovery_key,
    restore_apply,
    restore_preview,
    verify_backup,
)


def passphrase(args: argparse.Namespace) -> str:
    value = args.passphrase or os.environ.get("WHITENIGHT_BACKUP_KEY")
    if not value:
        print("缺少恢复密钥：--passphrase 或 WHITENIGHT_BACKUP_KEY", file=sys.stderr)
        raise SystemExit(2)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate-key")
    gen.add_argument("--words", type=int, default=0)

    backup = sub.add_parser("backup")
    backup.add_argument("--output", required=True, type=Path)
    backup.add_argument("--passphrase", default=None)

    for name in ("verify", "preview"):
        parser_cmd = sub.add_parser(name)
        parser_cmd.add_argument("--input", required=True, type=Path)
        parser_cmd.add_argument("--passphrase", default=None)

    restore = sub.add_parser("restore")
    restore.add_argument("--input", required=True, type=Path)
    restore.add_argument("--passphrase", default=None)

    args = parser.parse_args()
    if args.command == "generate-key":
        print(generate_recovery_key())
        print("请把恢复密钥保存在离线介质；本密钥独立于 Keychain 主密钥。", file=sys.stderr)
        return 0

    settings = load_settings()
    phrase = passphrase(args)
    if args.command == "backup":
        path = create_backup(settings, args.output, phrase)
        print(json.dumps({"backup": str(path), "size": path.stat().st_size}, ensure_ascii=False))
        return 0
    if args.command == "verify":
        print(json.dumps(verify_backup(args.input, phrase), ensure_ascii=False, indent=2))
        return 0
    if args.command == "preview":
        print(json.dumps(restore_preview(args.input, phrase), ensure_ascii=False, indent=2))
        return 0
    result = restore_apply(
        settings,
        args.input,
        phrase,
        service_health_url=os.environ.get("WHITENIGHT_URL", "http://127.0.0.1:8765"),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
