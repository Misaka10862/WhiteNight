"""pytest 共享夹具。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from whitenight.api.app import create_app
from whitenight.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    """隔离的临时配置：独立数据目录与内存 SQLite。"""
    return Settings(
        app_env="test",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'whitenight-test.db'}",
        keychain_backend="memory",
        log_level="WARNING",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
