"""Alembic 迁移入口：供应用启动时自动升级到 head。

命令行仍可用 ``uv run alembic upgrade head``；应用启动走同一 env.py。
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from whitenight.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_DIR = Path(__file__).resolve().parent / "migrations"


def upgrade_to_head(settings: Settings) -> None:
    """把数据库升级到最新迁移版本；幂等，可重复执行。"""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATION_DIR))
    config.attributes["whitenight_settings"] = settings
    command.upgrade(config, "head")
