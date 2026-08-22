#!/usr/bin/env bash
# 编译 WhiteNight 菜单栏状态入口（不修改系统，仅生成可执行文件）。
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${OUT:-$HOME/.local/bin/whitenight-menu-bar}"
mkdir -p "$(dirname "$OUT")"
swiftc -O scripts/menu_bar/MenuBarStatus.swift -o "$OUT"
echo "Built: $OUT"
echo "Run: $OUT"
