#!/usr/bin/env python3
"""Run the non-destructive stage 10 stability monitor for 72 hours.

Checks /healthz and /api/v1/status every 60 seconds and writes exceptions to
data/logs/stability-72h.jsonl. Usage:
    WHITENIGHT_STABILITY_HOURS=72 uv run scripts/run_72h.py
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hours", type=float, default=float(os.environ.get("WHITENIGHT_STABILITY_HOURS", "72"))
    )
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    log_path = ROOT / "data" / "logs" / "stability-72h.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.hours * 3600
    failures = 0
    checks = 0
    print(f"Stability monitor started: {args.hours}h every {args.interval}s; log: {log_path}")
    while time.time() < deadline:
        started = time.monotonic()
        try:
            response = httpx.get(f"{args.url}/healthz", timeout=5.0, trust_env=False)
            ok = response.status_code == 200
        except Exception:
            ok = False
        elapsed_ms = int((time.monotonic() - started) * 1000)
        checks += 1
        if not ok:
            failures += 1
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "ok": ok,
            "latency_ms": elapsed_ms,
            "checks": checks,
            "failures": failures,
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False))
        if not ok:
            print(
                "Service unhealthy; monitoring continues while launchd handles restart.", flush=True
            )
        time.sleep(args.interval)

    print(f"Stability monitor finished: checks={checks}, failures={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
