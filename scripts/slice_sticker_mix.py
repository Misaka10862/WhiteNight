#!/usr/bin/env python3
"""Create a new 3x3 sticker set by selecting cells from two sheets.

The selection string is row-major, e.g. ``112121122``.  Source sheets are
never modified.  The optional cell-6 cleanup masks the extra top-center ear in
the supplied first sheet while preserving the transparent background.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def _load(path: Path) -> Image.Image:
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"源图不存在或不是普通文件：{path}")
    with Image.open(path) as image:
        result = image.convert("RGBA")
    width, height = result.size
    if width % 3 or height % 3:
        raise SystemExit(f"九宫格尺寸必须能被 3 整除：{path} -> {width}x{height}")
    return result


def _remove_extra_ear(tile: Image.Image) -> Image.Image:
    """Erase the top-center extra ear from image-1 cell 6.

    The mask is deliberately limited to the triangular ear above the hairline;
    all other facial and clothing pixels remain untouched.
    """
    cleaned = tile.copy()
    mask = Image.new("L", cleaned.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([(116, 86), (154, 6), (216, 78), (205, 91), (128, 94)], fill=255)
    cleaned.paste((0, 0, 0, 0), mask=mask)
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image1", type=Path)
    parser.add_argument("image2", type=Path)
    parser.add_argument("selection", help="9 个字符，逐行表示选择图 1 或图 2")
    parser.add_argument("--output", type=Path, default=Path("/Users/misaka/Desktop/新表情包"))
    parser.add_argument("--no-ear-fix", action="store_true")
    args = parser.parse_args()

    selection = args.selection.strip()
    if len(selection) != 9 or any(char not in "12" for char in selection):
        raise SystemExit("selection 必须是恰好 9 个由 1/2 组成的字符")
    first_path = args.image1.expanduser().resolve()
    second_path = args.image2.expanduser().resolve()
    first, second = _load(first_path), _load(second_path)
    output = args.output.expanduser().resolve()
    if output == first_path.parent or output == second_path.parent:
        raise SystemExit("输出目录不能直接使用源图所在目录")
    output.mkdir(parents=True, exist_ok=True)
    cell_w, cell_h = first.width // 3, first.height // 3
    sources = {"1": first, "2": second}
    for index, choice in enumerate(selection, start=1):
        row, column = divmod(index - 1, 3)
        source = sources[choice]
        tile = source.crop(
            (column * cell_w, row * cell_h, (column + 1) * cell_w, (row + 1) * cell_h)
        )
        if index == 6 and choice == "1" and not args.no_ear_fix:
            tile = _remove_extra_ear(tile)
        target = output / f"sticker-{index:02d}.png"
        if target.exists():
            raise SystemExit(f"目标已存在，为避免覆盖请先人工处理：{target}")
        tile.save(target, format="PNG", optimize=True)
    print(f"已生成 9 张新表情：{output}")
    print(f"选择序列：{selection}（图1/图2，按行优先）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
