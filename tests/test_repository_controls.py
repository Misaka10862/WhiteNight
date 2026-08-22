"""Repository-local controls that replace the disabled hosted CI workflow."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".githooks" / "commit-msg"


def run_hook(tmp_path: Path, subject: str) -> subprocess.CompletedProcess[str]:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(f"{subject}\n\nA body may contain 中文.\n", encoding="utf-8")
    return subprocess.run(
        ["bash", str(HOOK), str(message)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_commit_hook_accepts_english_subject_and_chinese_body(tmp_path: Path) -> None:
    assert run_hook(tmp_path, "feat: add persona corpus tooling").returncode == 0


def test_commit_hook_rejects_chinese_subject(tmp_path: Path) -> None:
    result = run_hook(tmp_path, "feat: 添加人格语料工具")
    assert result.returncode != 0
    assert "Commit subjects must be English" in result.stderr
