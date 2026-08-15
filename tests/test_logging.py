"""日志脱敏测试。"""

from __future__ import annotations

import io
import logging

from whitenight.logging_config import redact, setup_logging


def test_redact_common_secrets() -> None:
    assert "***" in redact("authorization: Bearer abc123")
    assert "***" in redact("password=hunter2")
    assert "***" in redact("api_key='sk-verysecret'")
    assert "Bearer" not in redact("authorization: Bearer abc123")


def test_redact_keeps_regular_text() -> None:
    assert redact("今天天气不错，主人") == "今天天气不错，主人"


def test_handler_redacts_records() -> None:
    setup_logging(level="DEBUG")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    # RedactingFilter 由 setup_logging 安装于根 handler；这里单独验证过滤器本身。
    from whitenight.logging_config import RedactingFilter

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "token=verysecret", (), None)
    assert RedactingFilter().filter(record) is True
    assert record.msg == "token=***"
