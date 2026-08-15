"""pytest 共享夹具。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from whitenight.agent.service import DummyProvider
from whitenight.api.app import create_app
from whitenight.config import Settings
from whitenight.storage import Base
from whitenight.storage.engine import build_engine


@pytest.fixture
def settings(tmp_path) -> Settings:
    """隔离的临时配置：独立数据目录与 SQLite，关闭自动迁移由测试控制 schema。"""
    return Settings(
        app_env="test",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'whitenight-test.db'}",
        keychain_backend="memory",
        log_level="WARNING",
        auto_migrate=False,
    )


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    database_engine = build_engine(str(settings.database_url))
    Base.metadata.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    del engine  # schema 已建好；应用内部会打开自己的连接
    with TestClient(create_app(settings, model_provider=DummyProvider())) as test_client:
        yield test_client


@pytest.fixture
def chat_client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    """使用确定性 DummyProvider 的聊天链路客户端。"""
    del engine
    with TestClient(
        create_app(settings, model_provider=DummyProvider("好的，主人"))
    ) as test_client:
        yield test_client
