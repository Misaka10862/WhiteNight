#!/usr/bin/env python3
"""Encrypted backup CLI; recovery keys are read only from Keychain.

Initialize a key with generate-key, or import an existing key using configure-key.
Stop the service before restore; recover resumes an interrupted restore journal.
"""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

from whitenight.config import load_settings
from whitenight.credentials.keychain import get_keychain
from whitenight.storage.backup import (
    create_backup,
    recover_interrupted_restore,
    resolve_recovery_key,
    restore_apply,
    restore_preview,
    verify_backup,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-key")
    sub.add_parser("configure-key")
    sub.add_parser("recover")
    backup = sub.add_parser("backup")
    backup.add_argument("--output", required=True, type=Path)
    for name in ("verify", "preview", "restore"):
        parser_cmd = sub.add_parser(name)
        parser_cmd.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    settings = load_settings()
    if args.command == "generate-key":
        resolve_recovery_key(settings, create=True)
        print("Recovery key configured in Keychain; existing keys are retained.")
        return 0
    if args.command == "configure-key":
        phrase = getpass.getpass("Recovery key: ")
        if not phrase or phrase != getpass.getpass("Confirm recovery key: "):
            parser.error("Recovery key is empty or confirmation does not match")
        keychain = get_keychain(settings.keychain_backend)
        if keychain.get(settings.keychain_service, "backup-recovery-key"):
            parser.error("A recovery key already exists; manage replacement explicitly in Keychain")
        keychain.set(settings.keychain_service, "backup-recovery-key", phrase)
        print("Recovery key stored in Keychain.")
        return 0
    if args.command == "recover":
        print(json.dumps(recover_interrupted_restore(settings), ensure_ascii=False))
        return 0
    phrase = resolve_recovery_key(settings)
    if args.command == "backup":
        path = create_backup(settings, args.output, phrase)
        result: dict[str, object] = {"backup": str(path), "size": path.stat().st_size}
    elif args.command == "verify":
        result = verify_backup(args.input, phrase)
    elif args.command == "preview":
        result = restore_preview(args.input, phrase)
    else:
        result = restore_apply(settings, args.input, phrase)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
