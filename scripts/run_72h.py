#!/usr/bin/env python3
"""Sample structured service health without reading chat/task contents.

Run with ``.venv/bin/python scripts/run_72h.py --hours 72``. Short runs validate
the monitor only; a report certifies only its recorded sampling window.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MonitorConfig:
    hours: float = 72.0
    interval: float = 60.0
    stall_seconds: float = 1800.0
    max_rss_mib: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("hours", self.hours),
            ("interval", self.interval),
            ("stall_seconds", self.stall_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and greater than zero")
        if self.max_rss_mib is not None and (
            not math.isfinite(self.max_rss_mib) or self.max_rss_mib <= 0
        ):
            raise ValueError("max_rss_mib must be finite and greater than zero")


def process_rss(pid: int | None) -> int | None:
    """Read the service's RSS, never the monitor process's memory usage."""
    if pid is None or pid <= 0:
        return None
    try:
        output = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
        return int(output) * 1024 if output else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _health_state(value: object) -> str:
    if not isinstance(value, dict):
        return "unverified"
    if value.get("enabled") is False or value.get("status") == "disabled":
        return "disabled"
    if value.get("error") or value.get("configured") is False:
        return "unhealthy"
    flags = [
        value[key]
        for key in ("reachable", "available", "model_available", "ok", "logged_in")
        if key in value
    ]
    if any(flag is False for flag in flags):
        return "unhealthy"
    if flags and all(flag is True for flag in flags):
        return "healthy"
    return "unverified"


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


@dataclass
class ProbeResult:
    components: dict[str, str] = field(default_factory=dict)
    rss_bytes: int | None = None
    active_tasks: int = 0
    stalled_tasks: int = 0
    attention_tasks: int = 0
    version: str | None = None
    pid: int | None = None

    @property
    def complete(self) -> bool:
        return bool(self.components) and "unverified" not in self.components.values()

    @property
    def ok(self) -> bool:
        return self.complete and all(
            state in {"healthy", "disabled"} for state in self.components.values()
        )


class HealthProbe:
    def __init__(
        self,
        client: httpx.Client,
        *,
        rss_reader: Callable[[int | None], int | None] = process_rss,
        stall_seconds: float = 1800.0,
        pid: int | None = None,
    ) -> None:
        self.client = client
        self.rss_reader = rss_reader
        self.stall_seconds = stall_seconds
        self.pid = pid

    def _json(self, path: str) -> dict[str, Any] | None:
        try:
            response = self.client.get(path)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    def sample(self, now: datetime) -> ProbeResult:
        result = ProbeResult()
        try:
            reachable = self.client.get("/healthz").status_code == 200
        except httpx.HTTPError:
            reachable = False
        status = self._json("/api/v1/status")
        health = self._json("/api/v1/system/health")
        result.components["api"] = (
            "healthy" if reachable and status is not None and health is not None else "unhealthy"
        )
        health = health or {}
        status = status or {}
        result.components["database"] = _health_state(health.get("database"))
        result.components["model"] = _health_state(health.get("model"))
        delegates = health.get("delegates")
        if isinstance(delegates, dict):
            for name in ("codex", "hermes"):
                if name in delegates:
                    result.components[f"delegate.{name}"] = _health_state(delegates[name])
        else:
            result.components["delegates"] = "unverified"
        onebot = health.get("onebot")
        if isinstance(onebot, dict) and onebot.get("enabled") is False:
            result.components["onebot"] = "disabled"
        elif isinstance(onebot, dict) and onebot.get("enabled") is True:
            result.components["onebot"] = _health_state(onebot.get("health"))
        else:
            result.components["onebot"] = "unverified"

        monitor = status.get("monitor")
        monitor = monitor if isinstance(monitor, dict) else {}
        result.pid = self.pid or _integer(monitor.get("pid"))
        result.rss_bytes = _integer(monitor.get("rss_bytes")) or self.rss_reader(result.pid)
        result.rss_bytes = _integer(result.rss_bytes)
        result.components["resources"] = "healthy" if result.rss_bytes is not None else "unverified"
        version = status.get("version")
        if isinstance(version, str) and re.fullmatch(r"[\w.+-]{1,64}", version, flags=re.ASCII):
            result.version = version
        result.components["version"] = "healthy" if result.version else "unverified"
        tasks = monitor.get("tasks")
        result.components["tasks"] = "unverified"
        if isinstance(tasks, list) and monitor.get("tasks_complete") is True:
            result.components["tasks"] = "healthy"
            for task in tasks:
                if not isinstance(task, dict):
                    result.components["tasks"] = "unverified"
                    continue
                state = task.get("status")
                if state in {"awaiting_review", "cancel_failed"}:
                    result.attention_tasks += 1
                if state not in {"queued", "running", "cancelling"}:
                    continue
                result.active_tasks += 1
                try:
                    updated = datetime.fromisoformat(str(task["updated_at"]).replace("Z", "+00:00"))
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=UTC)
                    if (now - updated).total_seconds() > self.stall_seconds:
                        result.stalled_tasks += 1
                except (ValueError, KeyError, TypeError):
                    result.components["tasks"] = "unverified"
            if result.stalled_tasks or result.attention_tasks:
                result.components["tasks"] = "unhealthy"
        return result


def git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run_monitor(
    config: MonitorConfig,
    probe: HealthProbe,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    emit: Callable[[dict[str, Any]], None] = lambda record: print(json.dumps(record)),
    revision: Callable[[], str] = git_revision,
) -> dict[str, Any]:
    run_id = str(uuid4())
    start = monotonic()
    start_at = utcnow()
    duration = config.hours * 3600
    deadline = start + duration
    start_revision = revision()
    expected_samples = max(2, math.ceil(duration / config.interval) + 1)
    emit(
        {
            "kind": "start",
            "run_id": run_id,
            "ts": start_at.isoformat(),
            "revision": start_revision,
            "criteria": asdict(config),
            "expected_samples": expected_samples,
        }
    )
    samples = valid = failures = gaps = restarts = 0
    previous_at: datetime | None = None
    previous_pid: int | None = None
    rss_values: list[int] = []
    versions: set[str] = set()
    while True:
        sampled = monotonic()
        sampled_at = utcnow()
        if previous_at is not None:
            gap = (sampled_at - previous_at).total_seconds()
            if gap < 0 or gap > min(config.interval, duration) * 1.5:
                gaps += 1
        result = probe.sample(sampled_at)
        if result.rss_bytes is not None:
            rss_values.append(result.rss_bytes)
            if (
                config.max_rss_mib is not None
                and result.rss_bytes > config.max_rss_mib * 1024 * 1024
            ):
                result.components["resources"] = "unhealthy"
        if result.version:
            versions.add(result.version)
        if previous_pid and result.pid and previous_pid != result.pid:
            restarts += 1
        previous_pid = result.pid or previous_pid
        previous_at = sampled_at
        samples += 1
        valid += int(result.complete)
        failures += int("unhealthy" in result.components.values())
        record = {
            "kind": "sample",
            "run_id": run_id,
            "ts": sampled_at.isoformat(),
            "sample": samples,
            "ok": result.ok,
            "complete": result.complete,
            "latency_ms": round((monotonic() - sampled) * 1000),
            **asdict(result),
        }
        emit(record)
        if sampled >= deadline:
            break
        # Keep an absolute schedule and skip missed slots; never fabricate catch-up samples.
        now = monotonic()
        next_sample = min(
            start + (math.floor((now - start) / config.interval) + 1) * config.interval, deadline
        )
        sleep(max(0.0, next_sample - now))

    end_revision = revision()
    complete = (
        valid >= expected_samples
        and gaps == 0
        and len(versions) == 1
        and start_revision == end_revision
        and start_revision != "unknown"
    )
    outcome = "failed" if failures else ("passed" if complete else "inconclusive")
    report: dict[str, Any] = {
        "kind": "summary",
        "run_id": run_id,
        "started_at": start_at.isoformat(),
        "ended_at": utcnow().isoformat(),
        "requested_hours": config.hours,
        "observed_seconds": monotonic() - start,
        "start_revision": start_revision,
        "end_revision": end_revision,
        "service_versions": sorted(versions),
        "samples": samples,
        "valid_samples": valid,
        "expected_samples": expected_samples,
        "failures": failures,
        "sampling_gaps": gaps,
        "observed_restarts": restarts,
        "rss_first_bytes": rss_values[0] if rss_values else None,
        "rss_last_bytes": rss_values[-1] if rss_values else None,
        "rss_peak_bytes": max(rss_values) if rss_values else None,
        "outcome": outcome,
        "acceptance": "sampled window only; missing coverage is never success",
    }
    emit(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=float, default=os.environ.get("WHITENIGHT_STABILITY_HOURS", "72")
    )
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--stall-seconds", type=float, default=1800.0)
    parser.add_argument("--max-rss-mib", type=float)
    parser.add_argument(
        "--pid", type=int, help="Service PID override; never defaults to the monitor PID"
    )
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data" / "logs" / "stability-72h.jsonl"
    )
    args = parser.parse_args()
    try:
        config = MonitorConfig(args.hours, args.interval, args.stall_seconds, args.max_rss_mib)
        if args.pid is not None and args.pid <= 0:
            raise ValueError("pid must be greater than zero")
    except ValueError as exc:
        parser.error(str(exc))
    log_path = args.output
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(record: dict[str, Any]) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False), flush=True)

    with httpx.Client(base_url=args.url, timeout=30.0, trust_env=False) as client:
        probe = HealthProbe(client, stall_seconds=config.stall_seconds, pid=args.pid)
        report = run_monitor(config, probe, emit=emit)
    return {"passed": 0, "failed": 1, "inconclusive": 2}[report["outcome"]]


if __name__ == "__main__":
    raise SystemExit(main())
