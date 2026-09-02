#!/usr/bin/env python3
"""Slice a transparent 3x3 sticker sheet into ``data/stickers``.

The importer is intentionally deterministic: it never calls an image model,
never overwrites existing files, and refuses path traversal in its output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from whitenight.stickers.catalog import StickerRecord

DEFAULT_LABELS = (
    ("开心卖萌", ("开心", "卖萌", "亲昵"), ("严肃", "难过")),
    ("生气抗议", ("生气", "不满", "抗议"), ("平静", "正式任务")),
    ("兴奋欢呼", ("开心", "兴奋", "欢呼"), ("悲伤", "严肃")),
    ("惊讶委屈", ("惊讶", "委屈", "意外"), ("平静", "普通确认")),
    ("得意赞同", ("得意", "调皮", "赞同"), ("严肃", "悲伤")),
    ("困倦想睡", ("困倦", "晚安", "想睡"), ("紧急", "高强度任务")),
    ("害羞感动", ("害羞", "感动", "被夸"), ("严肃", "紧急")),
    ("无聊发呆", ("无聊", "发呆", "无语"), ("紧急", "需要明确答复")),
    ("激动加油", ("激动", "加油", "鼓励"), ("悲伤", "严肃")),
)


def _trim_alpha(tile: Image.Image, threshold: int) -> Image.Image:
    alpha = tile.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > threshold else 0)
    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError("网格单元没有可见内容")
    return tile.crop(bbox)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="透明背景的 3x3 PNG")
    parser.add_argument("--output", type=Path, default=Path("data/stickers"))
    parser.add_argument("--alpha-threshold", type=int, default=0, choices=range(0, 256))
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise SystemExit(f"素材不存在或不是普通文件：{source}")
    if output == source or source.is_relative_to(output):
        raise SystemExit("输出目录不能包含源文件")

    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    width, height = image.size
    if width % 3 or height % 3:
        raise SystemExit(f"图片尺寸必须能被 3 整除，当前为 {width}x{height}")
    cell_w, cell_h = width // 3, height // 3
    records: list[StickerRecord] = []
    files: list[tuple[Path, Image.Image]] = []
    for index, (label, use_when, avoid_when) in enumerate(DEFAULT_LABELS, start=1):
        row, column = divmod(index - 1, 3)
        tile = image.crop(
            (column * cell_w, row * cell_h, (column + 1) * cell_w, (row + 1) * cell_h)
        )
        trimmed = _trim_alpha(tile, args.alpha_threshold)
        sticker_id = f"sticker-{index:02d}"
        relative = Path(f"{sticker_id}.png")
        records.append(
            StickerRecord(
                id=sticker_id,
                file=relative.as_posix(),
                label=label,
                use_when=list(use_when),
                avoid_when=list(avoid_when),
            )
        )
        files.append((output / relative, trimmed))

    manifest_path = output / "catalog.json"
    conflicts = [path for path in [manifest_path, *(path for path, _ in files)] if path.exists()]
    if conflicts:
        joined = "\n".join(str(path) for path in conflicts)
        raise SystemExit(f"目标已存在；为避免覆盖，请先人工处理这些文件：\n{joined}")

    output.mkdir(parents=True, exist_ok=True)
    for path, sticker in files:
        sticker.save(path, format="PNG", optimize=True)
    manifest_path.write_text(
        json.dumps(
            {"version": 1, "stickers": [record.model_dump(mode="json") for record in records]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"已生成 {len(files)} 张表情：{output}")
    print(f"目录清单：{manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
