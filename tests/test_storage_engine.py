"""存储引擎测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from whitenight.storage.engine import (
    StorageConfigurationError,
    backend_of,
    build_engine,
    ping,
    resolve_database_key,
)


def test_backend_detection() -> None:
    assert backend_of("sqlite:///data/x.db") == "sqlite"
    assert backend_of("sqlcipher:///data/x.db") == "sqlcipher"


def test_sqlite_engine_creates_parent_dir(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'nested' / 'dir' / 'x.db'}"
    engine = build_engine(url)
    try:
        assert ping(engine)
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    finally:
        engine.dispose()


def test_sqlcipher_without_driver_explains_extra(tmp_path: Path) -> None:
    url = f"sqlcipher:///{tmp_path / 'x.db'}"
    with pytest.raises(StorageConfigurationError, match="sqlcipher"):
        build_engine(url, key="k")


def test_resolve_database_key_env_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHITENIGHT_DATABASE_KEY", "env-key")
    assert resolve_database_key("sqlcipher:///x.db") == "env-key"


def test_resolve_database_key_plain_sqlite_is_none() -> None:
    assert resolve_database_key("sqlite:///x.db") is None
