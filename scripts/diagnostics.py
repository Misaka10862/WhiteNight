#!/usr/bin/env python3
"""Run read-only WhiteNight diagnostics.

Checks database integrity/migrations/disk, Ollama, Codex MCP, Hermes Gateway,
pending approvals, attachment usage, and recent logs.
Usage: uv run scripts/diagnostics.py [--json]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

from whitenight.config import load_settings
from whitenight.policy.approvals import ApprovalService
from whitenight.storage.backup import database_path
from whitenight.storage.engine import backend_of, build_engine, ping


def cmd(*args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)
        return result.returncode, (result.stdout or result.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    report: dict[str, object] = {
        "env": settings.app_env,
        "host": settings.host,
        "port": settings.port,
    }

    if backend_of(str(settings.database_url)) == "sqlite":
        db_path = database_path(settings)
        report["database"] = {"path": str(db_path), "exists": db_path.exists()}
        if db_path.exists():
            connection = sqlite3.connect(str(db_path))
            try:
                report["database"]["integrity"] = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
                version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
                report["database"]["alembic_version"] = version[0] if version else None
            except Exception as exc:
                report["database"]["error"] = str(exc)
            finally:
                connection.close()
    engine = build_engine(str(settings.database_url))
    try:
        report["database"]["reachable"] = ping(engine)
        approvals = ApprovalService(engine)
        report["approvals_pending"] = len(approvals.list_pending())
    finally:
        engine.dispose()

    _total, used, free = shutil.disk_usage(Path.cwd())
    report["disk"] = {"free_gib": round(free / 1024**3, 1), "used_gib": round(used / 1024**3, 1)}
    attachments = settings.data_dir / "attachments"
    if attachments.exists():
        size = sum(path.stat().st_size for path in attachments.rglob("*") if path.is_file())
        report["attachments"] = {"files": len(list(attachments.rglob("*"))), "bytes": size}

    code, text = cmd("ollama", "list")
    report["ollama"] = {"ok": code == 0, "detail": text[:400]}
    code, text = cmd("codex", "--version")
    report["codex"] = {"ok": code == 0, "detail": text[:200]}
    code, text = cmd("hermes", "--version")
    report["hermes"] = {"ok": code == 0, "detail": text[:200]}

    log_path = settings.data_dir / "logs" / "whitenight.log"
    if log_path.exists():
        report["log_tail"] = "\n".join(
            log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
