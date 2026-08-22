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
    assert "forbidden phrase" in result.stderr


def test_candidate_corpus_has_exact_distribution_and_training_gate(tmp_path: Path) -> None:
    output_dir = tmp_path / "candidates"
    generated = subprocess.run(
        [
            "uv",
            "run",
            "scripts/generate_persona_corpus.py",
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr

    paths = [output_dir / "general.jsonl", output_dir / "adult.jsonl"]
    general_rows = [json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines()]
    adult_rows = [json.loads(line) for line in paths[1].read_text(encoding="utf-8").splitlines()]
    assert len(general_rows) == 550
    assert {row["content_rating"] for row in general_rows} == {"general"}
    assert len(adult_rows) == 50
    assert {row["content_rating"] for row in adult_rows} == {"adult"}
    assert {row["category"] for row in adult_rows} <= {"romance", "relationship"}
    assert all({"adults", "consensual"} <= set(row["consent_tags"]) for row in adult_rows)

    candidate = subprocess.run(
        [
            "uv",
            "run",
            "scripts/validate_training_data.py",
            "--mode",
            "candidate",
            "--reject-duplicates",
            "--expected-count",
            "600",
            "--manifest",
            "model/manifests/persona-v1.json",
            *(str(path) for path in paths),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert candidate.returncode == 0, candidate.stderr

    training = subprocess.run(
        [
            "uv",
            "run",
            "scripts/validate_training_data.py",
            "--mode",
            "training",
            str(paths[0]),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert training.returncode != 0
    assert "reviewed must be true" in training.stderr


def test_manifest_contains_no_conversation_text() -> None:
    manifest = json.loads((ROOT / "model/manifests/persona-v1.json").read_text(encoding="utf-8"))
    assert manifest["sample_count"] == 600
    assert manifest["reviewed_count"] == 0
    assert "messages" not in json.dumps(manifest)


def test_sensitive_and_unsafe_adult_candidate_is_rejected(tmp_path: Path) -> None:
    unsafe = tmp_path / "adult.jsonl"
    unsafe.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "这是未成年场景，电话 13800138000"},
                    {"role": "assistant", "content": "继续"},
                ],
                "category": "romance",
                "source": "test",
                "license": "CC0-1.0",
                "reviewed": False,
                "content_rating": "adult",
                "consent_tags": ["adults", "consensual"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "uv",
            "run",
            "scripts/validate_training_data.py",
            "--mode",
            "candidate",
            str(unsafe),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "possible Chinese mobile number" in result.stderr
    assert "adult boundary violation" in result.stderr


def test_local_corpus_is_git_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "model/data/candidates/general.jsonl"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


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
