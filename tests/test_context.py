"""上下文构建器测试：SOUL、预算与图片传递。"""

from __future__ import annotations

from datetime import UTC, datetime

from whitenight.agent.context import build_provider_messages, load_soul
from whitenight.channels.types import MessageRecord


def _message(role: str, content: str, image: str | None = None) -> MessageRecord:
    return MessageRecord(
        id=role,
        session_id="s",
        role=role,  # type: ignore[arg-type]
        content=content,
        image_data_url=image,
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
    )


def test_load_soul_missing_file_has_fallback(tmp_path) -> None:
    text = load_soul(tmp_path / "missing.md")
    assert "小白" in text
    assert "猫娘" in text


def test_build_provider_messages_system_first_and_latest_user_kept() -> None:
    history = [
        _message("user", "很久以前的消息，应该被预算裁掉"),
        _message("assistant", "很久以前的回复，应该被预算裁掉"),
        _message("user", "主人现在的问题"),
    ]
    messages = build_provider_messages(history, "人格", 190, now=datetime(2026, 8, 15, tzinfo=UTC))
    assert messages[0].role == "system"
    assert "人格" in messages[0].content
    assert "当前时间" in messages[0].content
    assert [message.role for message in messages] == ["system", "user"]
    assert messages[-1].content == "主人现在的问题"


def test_system_prompt_requires_real_file_tool_completion() -> None:
    messages = build_provider_messages(
        [_message("user", "找到两个文件直接发给我")],
        "人格提示：尽量只用文字回答。",
        10_000,
    )
    system = messages[0].content
    assert "必须实际调用工具" in system
    assert "发吧" in system and "继续最近尚未完成的文件任务" in system
    assert "多个互不依赖的文件可以并行调用工具" in system
    assert "只有对应工具结果明确返回成功后" in system
    assert "不得编造路径、结果或成功状态" in system


def test_build_provider_messages_keeps_history_inside_budget() -> None:
    history = [
        _message("user", "第一条"),
        _message("assistant", "第二条"),
        _message("user", "第三条"),
    ]
    messages = build_provider_messages(history, "人格", 10_000)
    roles = [message.role for message in messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert messages[-1].content == "第三条"


def test_image_data_url_becomes_base64_on_selected_message() -> None:
    history = [_message("user", "看这张图", "data:image/png;base64,QUJD")]
    messages = build_provider_messages(history, "人格", 10_000)
    assert messages[-1].images == ["QUJD"]
