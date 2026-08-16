"""Alembic 迁移环境。

统一从 WhiteNight 配置读取数据库 URL：环境变量 > YAML > 默认值。
SQLCipher 主密钥按 storage.engine.resolve_database_key 的同一规则解析。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from whitenight.config import load_settings
from whitenight.storage import Base
from whitenight.storage.engine import build_engine, resolve_database_key

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False：迁移日志配置不应禁掉已初始化的业务 logger，
    # 否则启动后 QQ 消息等 INFO 日志会全部丢失。
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# 应用内自动迁移通过 config.attributes 注入具体 Settings；
# CLI 运行时回退到全局配置分层（环境变量 > YAML > 默认值）。
settings = config.attributes.get("whitenight_settings") or load_settings()

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL，不连接数据库。"""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：按 URL 选择 sqlite3 或 sqlcipher3 驱动。"""
    engine = build_engine(settings.database_url, key=resolve_database_key(settings.database_url))

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
