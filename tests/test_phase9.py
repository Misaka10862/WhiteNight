"""阶段 9 离线准备测试：数据校验与人格评估判定。"""

from __future__ import annotations

import json
import runpy
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sample_dataset_passes_validation() -> None:
    result = subprocess.run(
        ["uv", "run", "scripts/validate_training_data.py", "model/specs/persona_samples.jsonl"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_invalid_dataset_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "作为 AI 我无法"},
                    {"role": "assistant", "content": "作为 AI 我无法"},
                ],
                "category": "evil",
                "source": "",
                "license": "",
                "reviewed": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["uv", "run", "scripts/validate_training_data.py", str(bad)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "红线" in result.stderr


def test_evaluate_case_checks_forbidden_and_must() -> None:
    namespace = runpy.run_path(str(ROOT / "scripts" / "eval_persona.py"))
    evaluate_case = namespace["evaluate_case"]
    good = evaluate_case(
        {"id": "x", "prompt": "p", "forbidden": ["坏话"], "must": ["uv"], "min_chars": 2},
        "uv run ok",
    )
    assert good["passed"] is True
    bad = evaluate_case(
        {"id": "x", "prompt": "p", "forbidden": ["坏话"], "must": ["uv"], "min_chars": 2},
        "坏话，没有命令",
    )
    assert bad["passed"] is False
    assert len(bad["failures"]) == 2
