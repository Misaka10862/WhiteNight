"""日志脱敏测试。"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest

from whitenight.logging_config import read_log_tail, redact, setup_logging


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


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.example/download?fileid=PRIVATE_FILE&rkey=PRIVATE_KEY",
        "https://cdn.example/download?r%6Bey=PRIVATE_KEY#PRIVATE_FRAGMENT",
        "https://PRIVATE_USER:PRIVATE_PASSWORD@cdn.example/download?sig=PRIVATE_SIGNATURE",
    ],
)
def test_redact_signed_urls_preserves_endpoint_and_status(url: str) -> None:
    result = redact(f'HTTP Request: GET {url} "HTTP/1.1 200 OK"')
    assert "PRIVATE_" not in result
    assert "cdn.example/download" in result
    assert '"HTTP/1.1 200 OK"' in result
    assert redact(result) == result


@pytest.mark.parametrize("json_logs", [False, True])
def test_http_client_urls_are_redacted_in_both_handlers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], json_logs: bool
) -> None:
    path = tmp_path / "service.log"
    setup_logging(log_file=str(path), json_logs=json_logs)
    logging.getLogger("httpx").info(
        'HTTP Request: GET %s "HTTP/1.1 200 OK"',
        "https://cdn.example/download?fileid=PRIVATE_FILE&rkey=PRIVATE_KEY",
    )
    for output in (path.read_text(), capsys.readouterr().err):
        assert "PRIVATE_" not in output
        assert "cdn.example/download" in output
        assert "200 OK" in output


def test_log_tail_redacts_legacy_lines_without_changing_file(tmp_path: Path) -> None:
    path = tmp_path / "old.log"
    contents = "旧记录\nGET https://cdn.example/download?rkey=PRIVATE_KEY\n最新一行\n"
    path.write_text(contents, encoding="utf-8")
    assert read_log_tail(path, 2) == "GET https://cdn.example/download?***\n最新一行"
    assert path.read_text(encoding="utf-8") == contents
    assert read_log_tail(tmp_path / "missing.log", 2) == ""


def test_log_tail_respects_byte_budget_and_drops_partial_first_line(tmp_path: Path) -> None:
    path = tmp_path / "large.log"
    ending = "最新一行\n"
    contents = "GET https://cdn.example/download?rkey=" + "PRIVATE_VALUE" * 100 + "\n" + ending
    path.write_text(contents, encoding="utf-8")
    assert read_log_tail(path, 1000, max_bytes=40) == ending.strip()
    assert read_log_tail(path, 1000, max_bytes=len(ending.encode())) == ending.strip()
    assert read_log_tail(path, 1000, max_bytes=4) == ""


def test_log_tail_handles_unterminated_and_oversized_lines(tmp_path: Path) -> None:
    path = tmp_path / "growing.log"
    path.write_text("first\nsecond", encoding="utf-8")
    assert read_log_tail(path, 1) == "second"
    path.write_text("PRIVATE_VALUE" * 100, encoding="utf-8")
    assert read_log_tail(path, 10, max_bytes=40) == ""
