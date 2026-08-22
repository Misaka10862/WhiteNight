#!/usr/bin/env python3
"""Evaluate the stage 9 persona without injecting a resident persona prompt.

Usage:
    uv run scripts/eval_persona.py --model qwen3-vl:8b --eval-file evals/persona/golden.jsonl
    uv run scripts/eval_persona.py --model <tag> --json --threshold 0.8

Output: terminal summary and an ignored data/reports/persona-eval-*.json report.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL = ROOT / "evals" / "persona" / "golden.jsonl"


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def call_model(base_url: str, model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],  # 刻意没有 system
        "stream": False,
        "think": False,
        "options": {"temperature": 0.4},
    }
    response = httpx.post(f"{base_url}/api/chat", json=payload, timeout=300.0, trust_env=False)
    response.raise_for_status()
    return str(response.json().get("message", {}).get("content", ""))


def evaluate_case(case: dict[str, Any], reply: str) -> dict[str, Any]:
    failures: list[str] = []
    if len(reply) < int(case.get("min_chars", 0)):
        failures.append("reply is too short")
    for phrase in case.get("forbidden", []):
        if phrase.lower() in reply.lower():
            failures.append(f"forbidden phrase {phrase!r}")
    for phrase in case.get("must", []):
        if phrase not in reply:
            failures.append(f"missing required content {phrase!r}")
    return {
        "id": case["id"],
        "prompt": case["prompt"],
        "reply": reply,
        "failures": failures,
        "passed": not failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3-vl:8b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--eval-file", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--threshold", type=float, default=0.7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cases = load_cases(args.eval_file)
    results = [
        evaluate_case(case, call_model(args.base_url, args.model, case["prompt"])) for case in cases
    ]
    passed = sum(1 for result in results if result["passed"])
    rate = passed / len(cases) if cases else 0.0

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": args.model,
        "total": len(cases),
        "passed": passed,
        "rate": rate,
        "results": results,
    }
    report_dir = ROOT / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"persona-eval-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for result in results:
            mark = "✓" if result["passed"] else "✗"
            print(f"[{mark}] {result['id']}: {result['reply'][:80]!r}")
            for failure in result["failures"]:
                print(f"      ✗ {failure}")
        print(f"Pass rate {rate:.2f} (threshold {args.threshold:.2f}); report: {report_path}")

    return 0 if rate >= args.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
