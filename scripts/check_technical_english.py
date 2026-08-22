#!/usr/bin/env python3
"""Reject CJK text in technical prose while preserving approved Chinese surfaces."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u3400-\u9fff]")

EXCLUDED_PATHS = {
    "AGENTS.md",
    "README-zh.md",
    "SOUL.md",
    "构建计划.md",
    "model/specs/persona_samples.jsonl",
}
EXCLUDED_PREFIXES = (
    "apps/web/",
    "evals/",
    "model/data/",
    "src/",
    "tests/",
)
TECHNICAL_SUFFIXES = {".md", ".toml", ".yaml", ".yml", ".sh", ".command"}


def tracked_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return [ROOT / item.decode() for item in output.split(b"\0") if item]


def is_comment(path: Path, line: str) -> bool:
    stripped = line.lstrip()
    if path.suffix in {".sh", ".command", ".yaml", ".yml", ".toml"}:
        return stripped.startswith("#")
    return False


def main() -> int:
    failures: list[str] = []
    for path in tracked_files():
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            continue
        if relative in EXCLUDED_PATHS or relative.startswith(EXCLUDED_PREFIXES):
            continue
        if path.suffix not in TECHNICAL_SUFFIXES:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if CJK.search(line) and not is_comment(path, line):
                failures.append(f"{relative}:{number}: {line.strip()}")

    if failures:
        print("Chinese text remains in English-only technical content:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("Technical English audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
