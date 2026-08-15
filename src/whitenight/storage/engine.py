"""数据库引擎工厂。

支持两种 URL：
- ``sqlite:///path`` —— 开发/测试，启用 WAL；
- ``sqlcipher:///path`` —— 生产加密库，需要安装 ``whitenight[sqlcipher]``，
  通过连接事件执行 ``PRAGMA key``，主密钥绝不写入连接串或日志。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url

Backend = Literal["sqlite", "sqlcipher"]


class StorageConfigurationError(RuntimeError):
    """数据库 URL、驱动或密钥配置错误。"""


def backend_of(database_url: str) -> Backend:
    return "sqlcipher" if make_url(database_url).get_backend_name() == "sqlcipher" else "sqlite"


def _ensure_sqlite_dir(database_url: str) -> None:
    url = make_url(database_url)
    if url.database and url.database != ":memory:":
        Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _enable_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    """SQLite 连接级 PRAGMA：WAL、外键、忙等待。SQLCipher 连接同样适用。"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def build_engine(database_url: str, key: str | None = None) -> Engine:
    """按 URL 构建 SQLAlchemy Engine。"""
    url = make_url(database_url)
    backend = url.get_backend_name()

    if backend == "sqlcipher":
        try:
            import sqlcipher3  # type: ignore[import-not-found]
        except ImportError as exc:
            raise StorageConfigurationError(
                "使用 sqlcipher:// 需要安装可选依赖：uv sync --extra sqlcipher"
            ) from exc
        if not key:
            raise StorageConfigurationError("sqlcipher:// 数据库必须提供主密钥（来自 Keychain）")
        sqlite_url = url.set(drivername="sqlite")
        _ensure_sqlite_dir(database_url)
        engine = create_engine(
            sqlite_url,
            module=sqlcipher3,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _set_key(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                # SQLCipher 的 PRAGMA key 不接受绑定参数；密钥经过单引号转义后拼接，
                # 且该语句从不进入日志。
                escaped_key = key.replace("'", "''")
                cursor.execute(f"PRAGMA key = '{escaped_key}'")
            finally:
                cursor.close()

        event.listen(engine, "connect", _enable_sqlite_pragmas)
        return engine

    if backend == "sqlite":
        _ensure_sqlite_dir(database_url)
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
        )
        event.listen(engine, "connect", _enable_sqlite_pragmas)
        return engine

    raise StorageConfigurationError(f"不支持的数据库 backend：{backend}")


def resolve_database_key(
    database_url: str,
    keychain_backend: str = "macos",
    keychain_service: str = "com.whitenight.credentials",
) -> str | None:
    """为加密数据库解析主密钥。

    优先级：``WHITENIGHT_DATABASE_KEY`` 环境变量（仅用于 CI 与恢复流程）>
    macOS Keychain（生产默认）。明文密钥绝不进入日志。
    """
    if backend_of(database_url) != "sqlcipher":
        return None
    env_key = os.environ.get("WHITENIGHT_DATABASE_KEY")
    if env_key:
        return env_key
    # 延迟导入，避免加载存储模块时强依赖 Keychain 实现。
    from whitenight.credentials.keychain import KeychainError, get_keychain

    try:
        return get_keychain(keychain_backend).get(keychain_service, "database-master-key")
    except KeychainError as exc:
        raise StorageConfigurationError(f"无法从 Keychain 读取数据库主密钥：{exc}") from exc


def ping(engine: Engine) -> bool:
    """轻量连通性检查，不触发业务查询。"""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # 状态接口需要吞掉并报告
        return False
