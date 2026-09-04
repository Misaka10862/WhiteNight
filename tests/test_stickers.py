from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import httpx
from PIL import Image

from whitenight.agent.service import ChatService
from whitenight.channels.onebot import ChannelSessionStore, OneBotAdapter, OneBotSender
from whitenight.models.base import (
    ModelCapabilities,
    ModelChunk,
    ProviderMessage,
    ToolCall,
    ToolSpec,
)
from whitenight.policy.approvals import ApprovalService
from whitenight.policy.audit import AuditService
from whitenight.policy.engine import PolicyEngine
from whitenight.stickers import StickerCatalog, StickerRecord
from whitenight.storage.sessions import SessionStore
from whitenight.tools import StickerSendTool, ToolExecutor, ToolRegistry


def _catalog(tmp_path: Path) -> StickerCatalog:
    root = tmp_path / "stickers"
    root.mkdir()
    image = Image.new("RGBA", (12, 10), (255, 0, 0, 255))
    image.save(root / "sticker-01.png")
    (root / "catalog.json").write_text(
        json.dumps(
            {
                "version": 1,
                "stickers": [
                    StickerRecord(
                        id="sticker-01",
                        file="sticker-01.png",
                        label="开心卖萌",
                        use_when=["开心"],
                        avoid_when=["严肃"],
                        emoji_id="123",
                        emoji_package_id="9",
                    ).model_dump(mode="json")
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return StickerCatalog(root)


def test_importer_slices_transparent_grid(tmp_path: Path) -> None:
    source = tmp_path / "sheet.png"
    sheet = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    for row in range(3):
        for column in range(3):
            for x in range(column * 4 + 1, column * 4 + 3):
                for y in range(row * 4 + 1, row * 4 + 3):
                    sheet.putpixel((x, y), (255, 0, 0, 255))
    sheet.save(source)
    output = tmp_path / "out"
    subprocess.run(
        ["uv", "run", "scripts/import_stickers.py", str(source), "--output", str(output)],
        check=True,
    )
    assert len(list(output.glob("sticker-*.png"))) == 9
    with Image.open(output / "sticker-01.png") as image:
        assert image.size == (2, 2)
    catalog = StickerCatalog(output)
    assert catalog.records(native_only=True) == []
    assert not StickerSendTool(catalog, [10001]).available()


def test_catalog_validates_paths_and_renders_only_labels(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    assert catalog.get("sticker-01") is not None
    assert "sticker-01" in catalog.prompt_text()
    assert str(tmp_path) not in catalog.prompt_text()


def test_sticker_tool_is_auto_policy_and_strict_id(engine, settings, tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    approvals = ApprovalService(engine)
    executor = ToolExecutor(
        ToolRegistry([StickerSendTool(catalog, [10001])]),
        PolicyEngine(),
        approvals,
        AuditService(engine),
    )
    outcome = executor.execute(
        "channel.sticker.send",
        {"sticker_id": "sticker-01"},
        session_id="s1",
        channel="onebot",
        channel_target="10001",
    )
    assert outcome.status == "ok"
    assert outcome.result is not None
    assert outcome.result.metadata["sticker_id"] == "sticker-01"
    assert approvals.list_pending() == []
    assert (
        executor.execute(
            "channel.sticker.send",
            {"sticker_id": "/tmp/secret.png"},
            session_id="s1",
            channel="onebot",
            channel_target="10001",
        ).status
        == "error"
    )
    assert (
        executor.execute(
            "channel.sticker.send",
            {"sticker_id": "sticker-01"},
            session_id="s1",
            channel="onebot",
            channel_target="99999",
        ).status
        == "error"
    )


class StickerProvider:
    capabilities = ModelCapabilities(tools=True)

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ):
        assert tools and any(item.name == "channel.sticker.send" for item in tools)
        if not any(message.role == "tool" for message in messages):
            yield ModelChunk(
                done=True,
                tool_calls=[
                    ToolCall(
                        id="sticker-1",
                        name="channel.sticker.send",
                        arguments={"sticker_id": "sticker-01"},
                    )
                ],
            )
        else:
            yield ModelChunk(delta="今天很开心呀")
            yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class OrderedQQ:
    def __init__(self, record: StickerRecord) -> None:
        self.events: list[tuple[str, object]] = []
        self.record = record

    def send_private_message(self, user_id: int, text: str) -> int:
        self.events.append(("text", (user_id, text)))
        return 1

    def send_private_mface(
        self,
        user_id: int,
        *,
        segment_type: str,
        emoji_id: str,
        emoji_package_id: str | None,
        key: str | None,
    ) -> int:
        assert (segment_type, emoji_id, emoji_package_id, key) == (
            "mface",
            self.record.emoji_id,
            self.record.emoji_package_id,
            self.record.key,
        )
        self.events.append(("image", user_id))
        return 1


def test_qq_text_is_sent_before_selected_sticker(engine, settings, tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    store = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    approvals = ApprovalService(engine)
    registry = ToolRegistry([StickerSendTool(catalog, [10001])])
    executor = ToolExecutor(registry, PolicyEngine(), approvals, AuditService(engine))
    service = ChatService(
        store,
        StickerProvider(),
        settings,
        tool_registry=registry,
        tool_executor=executor,
        approvals=approvals,
        policy=PolicyEngine(),
        sticker_catalog=catalog,
    )
    sender = OrderedQQ(catalog.get("sticker-01"))  # type: ignore[arg-type]
    adapter = OneBotAdapter(
        settings.model_copy(
            update={"qq_enabled": True, "qq_owner_ids": [10001], "qq_rate_limit_seconds": 0}
        ),
        store,
        ChannelSessionStore(engine, store),
        service,
        approvals,
        sender=sender,  # type: ignore[arg-type]
        stickers=catalog,
    )
    event = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 9001,
        "user_id": 10001,
        "raw_message": "今天心情不错",
        "message": [{"type": "text", "data": {"text": "今天心情不错"}}],
    }
    result = asyncio.run(adapter.handle_event(event))
    assert result["status"] == "replied"
    assert [kind for kind, _value in sender.events] == ["text", "image"]


def test_onebot_sender_mface_segment() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"status": "ok", "retcode": 0}, request=request)

    sender = OneBotSender("http://mock", transport=httpx.MockTransport(handler))
    assert (
        sender.send_private_mface(
            10001,
            segment_type="mface",
            emoji_id="123",
            emoji_package_id="9",
        )
        == 1
    )
    assert captured["user_id"] == 10001
    segment = captured["message"][0]
    assert segment == {
        "type": "mface",
        "data": {"emoji_id": "123", "emoji_package_id": "9"},
    }


def test_onebot_sender_personal_qq_face_uses_animation_subtype() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"status": "ok", "retcode": 0}, request=request)

    sender = OneBotSender("http://mock", transport=httpx.MockTransport(handler))
    assert (
        sender.send_private_sticker(
            10001,
            segment_type="image",
            sub_type=1,
            url="https://p.qpic.cn/qq_expression/example/0",
        )
        == 1
    )
    assert captured["user_id"] == 10001
    assert captured["message"] == [
        {
            "type": "image",
            "data": {
                "file": "https://p.qpic.cn/qq_expression/example/0",
                "sub_type": 1,
                "summary": "[动画表情]",
            },
        }
    ]


def test_catalog_accepts_personal_qq_face_metadata(tmp_path: Path) -> None:
    root = tmp_path / "stickers"
    root.mkdir()
    Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(root / "face.png")
    (root / "catalog.json").write_text(
        json.dumps(
            {
                "version": 1,
                "stickers": [
                    StickerRecord(
                        id="face-01",
                        file="face.png",
                        label="卖萌",
                        segment_type="image",
                        sub_type=1,
                        native_url="https://p.qpic.cn/qq_expression/example/0",
                    ).model_dump(mode="json")
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    catalog = StickerCatalog(root)
    assert catalog.records(native_only=True)[0].native_ready
