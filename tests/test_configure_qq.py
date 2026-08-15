"""QQ 配置脚本测试：合并、备份、不覆盖无关键。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_configure_qq_merges_and_backs_up(tmp_path: Path) -> None:
    config = tmp_path / "whitenight.yaml"
    config.write_text("model_name: qwen3:8b\nqq_enabled: false\n", encoding="utf-8")
    result = subprocess.run(
        [
            "uv",
            "run",
            "scripts/configure_qq.py",
            "--owner",
            "10001",
            "--owner",
            "10002",
            "--config",
            str(config),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert data["qq_enabled"] is True
    assert data["qq_owner_ids"] == [10001, 10002]
    assert data["qq_onebot_api_url"] == "http://127.0.0.1:3000"
    assert data["model_name"] == "qwen3:8b"  # 无关配置不被覆盖
    backups = list(tmp_path.glob("whitenight.bak-*"))
    assert len(backups) == 1
