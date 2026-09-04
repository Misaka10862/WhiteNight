#!/usr/bin/env python3
"""Bind local sticker assets to the QQ account's saved custom faces.

NapCat exposes saved personal faces through ``fetch_custom_face_detail``.  The
returned URL is intentionally stored as delivery metadata: sending it with
``image/sub_type=1`` makes NapCat emit a QQ animated-face message, while the
local PNG remains only the catalog/reference asset.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from whitenight.channels.onebot.sender import OneBotSender
from whitenight.stickers.catalog import StickerRecord

_HINTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "抛媚眼": (("调皮", "亲昵"), ("严肃",)),
    "惊讶": (("惊讶", "意外"), ("平静",)),
    "欢呼": (("开心", "兴奋", "欢呼"), ("悲伤", "严肃")),
    "大哭": (("难过", "委屈"), ("开心", "正式任务")),
    "疑惑": (("疑惑", "不确定"), ("明确答复",)),
    "眼泪汪汪": (("委屈", "难过"), ("严肃",)),
    "心情复杂": (("纠结", "复杂"), ("紧急",)),
    "写代码": (("工作", "专注"), ("撒娇",)),
    "嫌弃": (("嫌弃", "吐槽"), ("严肃",)),
    "睡着": (("困倦", "晚安", "想睡"), ("紧急",)),
    "生气": (("生气", "不满", "抗议"), ("平静", "正式任务")),
    "认真": (("认真", "专注", "任务"), ("玩笑",)),
    "卖萌": (("开心", "卖萌", "亲昵"), ("严肃",)),
    "惊恐": (("害怕", "惊恐"), ("平静",)),
    "坏笑": (("得意", "调皮", "坏笑"), ("严肃",)),
    "嘲讽": (("吐槽", "嘲讽"), ("正式任务",)),
    "超害羞": (("害羞", "被夸", "感动"), ("严肃",)),
    "比耶": (("开心", "赞同", "庆祝"), ("悲伤",)),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:3000")
    parser.add_argument("--assets", type=Path, default=Path("data/stickers"))
    parser.add_argument("--catalog", type=Path, default=Path("data/stickers/catalog.json"))
    parser.add_argument("--count", type=int, default=200)
    args = parser.parse_args()

    assets = args.assets.expanduser().resolve()
    catalog_path = args.catalog.expanduser().resolve()
    if not assets.is_dir() or assets.is_symlink():
        raise SystemExit(f"素材目录不存在或不是普通目录：{assets}")
    try:
        details = OneBotSender(args.api_url).fetch_custom_face_detail(args.count)
    except Exception as exc:
        raise SystemExit(f"NapCat 返回失败：{exc}") from exc
    by_desc: dict[str, dict[str, Any]] = {}
    for detail in details:
        desc = detail.get("desc")
        url = detail.get("url")
        if (
            isinstance(desc, str)
            and desc
            and isinstance(url, str)
            and url.startswith(("http://", "https://"))
        ):
            if desc in by_desc:
                raise SystemExit(f"QQ 自定义表情备注重复，无法安全匹配：{desc}")
            by_desc[desc] = detail

    files = sorted(
        path
        for path in assets.iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix.lower() == ".png"
    )
    records: list[StickerRecord] = []
    missing: list[str] = []
    for index, path in enumerate(files, start=1):
        label = path.stem.removeprefix("sticker-")
        detail = by_desc.get(label)
        if detail is None:
            missing.append(label)
            continue
        use_when, avoid_when = _HINTS.get(label, ((label,), ("严肃",)))
        records.append(
            StickerRecord(
                id=f"sticker-{index:02d}",
                file=path.name,
                label=label,
                use_when=list(use_when),
                avoid_when=list(avoid_when),
                enabled=True,
                segment_type="image",
                sub_type=1,
                native_url=str(detail["url"]),
            )
        )
    if missing:
        raise SystemExit("以下本地素材没有匹配到 QQ 备注：" + "、".join(missing))
    if len(records) != 18:
        raise SystemExit(f"需要绑定 18 张素材，当前匹配 {len(records)} 张")

    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        json.dumps(
            {"version": 1, "stickers": [record.model_dump(mode="json") for record in records]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"已绑定 {len(records)} 张 QQ 原生动画表情：{catalog_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
