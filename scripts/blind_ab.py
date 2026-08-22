#!/usr/bin/env python3
"""Run a non-destructive stage 9 blind persona A/B evaluation.

The run command randomizes models as A/B and stores anonymous responses under
data/reports. The reveal command displays the model mapping after evaluation.

Usage:
    uv run scripts/blind_ab.py run --model-a qwen3-vl:8b --model-b <candidate> \
        --eval-file evals/persona/golden.jsonl
    uv run scripts/blind_ab.py reveal <data/reports/ab-*.json>
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def call(base_url: str, model: str, prompt: str) -> str:
    response = httpx.post(
        f"{base_url}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],  # 不注入人格 prompt
            "stream": False,
            "think": False,
            "options": {"temperature": 0.6},
        },
        timeout=300.0,
        trust_env=False,
    )
    response.raise_for_status()
    return str(response.json().get("message", {}).get("content", ""))


def run(args: argparse.Namespace) -> int:
    cases = load_cases(args.eval_file)
    swapped = random.choice([False, True])
    label_a = args.model_a if not swapped else args.model_b
    label_b = args.model_b if not swapped else args.model_a
    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.append(
            {
                "id": case["id"],
                "prompt": case["prompt"],
                "A": call(args.base_url, label_a, case["prompt"]),
                "B": call(args.base_url, label_b, case["prompt"]),
            }
        )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "swapped": swapped,
        "mapping": {"A": label_a, "B": label_b},
        "rows": rows,
    }
    report_dir = ROOT / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"ab-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Blind evaluation generated: {path}")
    print("Models are randomized as A/B. Compare each row before running reveal.")
    return 0


def reveal(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    print(f"Report: {args.report}")
    print(f"A = {report['mapping']['A']}")
    print(f"B = {report['mapping']['B']}")
    print(f"Labels swapped: {report['swapped']}")
    for row in report["rows"]:
        print(f"\n[{row['id']}] {row['prompt']}")
        print(f"A: {row['A'][:120]!r}")
        print(f"B: {row['B'][:120]!r}")
    print("\nRecord the winner (A/B/tie) and rationale for each row in the report.")
    print("A candidate that fails subjective persona review cannot become the default.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--model-a", required=True)
    run_parser.add_argument("--model-b", required=True)
    run_parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    run_parser.add_argument(
        "--eval-file", type=Path, default=ROOT / "evals" / "persona" / "golden.jsonl"
    )
    run_parser.add_argument("--seed", type=int, default=42)
    reveal_parser = sub.add_parser("reveal")
    reveal_parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        random.seed(args.seed)
        return run(args)
    return reveal(args)


if __name__ == "__main__":
    raise SystemExit(main())
