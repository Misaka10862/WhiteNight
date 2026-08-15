"""SQLCipher 引擎集成测试：需要安装可选依赖 ``uv sync --extra sqlcipher``。

未安装驱动时自动跳过（CI 已启用该 extra）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

pytest.importorskip("sqlcipher3", reason="需要 uv sync --extra sqlcipher")

from whitenight.storage import AppMeta
from whitenight.storage.engine import StorageConfigurationError, build_engine, ping


def test_sqlcipher_engine_roundtrip(tmp_path: Path) -> None:
    key = "test-master-key-0123456789"
    engine = build_engine(f"sqlcipher:///{tmp_path / 'encrypted.db'}", key=key)
    try:
        AppMeta.metadata.create_all(engine)
        assert ping(engine)
        with engine.begin() as connection:
            connection.execute(AppMeta.__table__.insert().values(key="phase1-probe", value="小白"))
        with engine.connect() as connection:
            row = connection.execute(select(AppMeta).where(AppMeta.key == "phase1-probe")).one()
            assert row.value == "小白"
    finally:
        engine.dispose()


def test_sqlcipher_wrong_key_fails(tmp_path: Path) -> None:
    engine = build_engine(f"sqlcipher:///{tmp_path / 'encrypted.db'}", key="right-key")
    AppMeta.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(AppMeta.__table__.insert().values(key="k", value="v"))
    engine.dispose()

    wrong = build_engine(f"sqlcipher:///{tmp_path / 'encrypted.db'}", key="wrong-key")
    try:
        assert not ping(wrong)
    finally:
        wrong.dispose()


def test_sqlcipher_requires_key(tmp_path: Path) -> None:
    with pytest.raises(StorageConfigurationError, match="主密钥"):
        build_engine(f"sqlcipher:///{tmp_path / 'x.db'}", key=None)
