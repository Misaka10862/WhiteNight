"""日志规范：统一入口、JSON 可选、默认脱敏。

敏感模式覆盖：api_key、token、secret、password、authorization 及其常见变体。
日志永远不直接打印数据库主密钥或服务凭据。
"""

from __future__ import annotations

import json
import logging
import logging.config
import re
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 命中 "authorization: Bearer xyz"、"password=abc"、"api_key" 这类形态。
_SECRET_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|auth(?:orization)?|token|secret|password|passwd|pwd|"
    r"db[_-]?key|master[_-]?key)\s*[\"']?\s*[:=]\s*[\"']?)([^\s\"',;]+)",
)


def redact(text: str) -> str:
    """把敏感赋值右侧替换为 ``***``，保留键名便于排查。"""
    text = re.sub(r"(?i)\bBearer\s+[^\s\"',;]+", "***", text)
    return _SECRET_PATTERN.sub(r"\1***", text)


class RedactingFilter(logging.Filter):
    """对所有日志记录做值脱敏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
            if record.exc_info:
                error_type, _value, tb = record.exc_info
                # Keep diagnostic locations, never exception bodies or source lines.
                frames = traceback.extract_tb(tb)
                locations = " -> ".join(
                    f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in frames
                )
                record.exc_text = f"{error_type.__name__ if error_type else 'Error'} [{locations}]"
                record.exc_info = None
        except Exception:  # 脱敏失败不应中断业务日志
            pass
        return True


class JsonFormatter(logging.Formatter):
    """结构化 JSON 行，供生产环境采集。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if record.exc_text:
            payload["exc"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    json_logs: bool = False,
    log_file: str | None = None,
) -> None:
    """幂等安装根日志配置。log_file 与 stdout 都经过同一脱敏过滤器。"""
    formatter: logging.Formatter
    if json_logs:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )

    root = logging.getLogger()
    root.handlers.clear()

    # 幂等恢复：之前可能有 fileConfig(disable_existing_loggers=True) 之类的配置
    # 把业务 logger 标记为 disabled；显式取消禁用，让 INFO 日志重新可达 root。
    for candidate in logging.Logger.manager.loggerDict.values():
        if isinstance(candidate, logging.Logger):
            candidate.disabled = False

    stream_handler: logging.Handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(RedactingFilter())
    root.addHandler(stream_handler)

    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(RedactingFilter())
        root.addHandler(file_handler)

    root.setLevel(level.upper())
