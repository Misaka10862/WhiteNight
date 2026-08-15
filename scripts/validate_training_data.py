#!/usr/bin/env python3
"""小白人格训练数据校验器（阶段 9，非破坏性）。

用法：
    uv run scripts/validate_training_data.py model/specs/persona_samples.jsonl
    uv run scripts/validate_training_data.py --reject-duplicates FILE...

规则见 model/specs/persona_data_spec.md；任何错误非零退出。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

CATEGORIES = {
    "chat",
    "coquetry",
    "comfort",
    "romance",
    "serious",
    "delegation",
    "progress",
    "correction",
    "relationship",
}
FORBIDDEN = [
    "作为 AI",
    "作为人工智能",
    "我无法",
    "抱歉，我不能",
    "api_key",
    "password",
    "token=",
]


def validate(paths: list[Path], reject_duplicates: bool) -> int:
    errors: list[str] = []
    seen: dict[str, str] = {}
    total = 0
    for path in paths:
        if not path.exists():
            errors.append(f"{path}: 文件不存在")
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            total += 1
            location = f"{path}:{line_number}"
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{location}: JSON 解析失败 {exc}")
                continue
            messages = item.get("messages")
            if not isinstance(messages, list) or len(messages) < 2:
                errors.append(f"{location}: messages 至少 2 条")
                continue
            if messages[0].get("role") != "user":
                errors.append(f"{location}: 首条必须是 user")
            for message in messages:
                role = message.get("role")
                if role not in {"user", "assistant"}:
                    errors.append(f"{location}: 非法 role {role!r}")
                    continue
                content = str(message.get("content", ""))
                if not content.strip():
                    errors.append(f"{location}: 存在空内容")
                if len(content) > 4000:
                    errors.append(f"{location}: 单条消息超过 4000 字符")
                lowered = content.lower()
                for phrase in FORBIDDEN:
                    if phrase.lower() in lowered:
                        errors.append(f"{location}: 命中红线短语 {phrase!r}")
            category = item.get("category")
            if category not in CATEGORIES:
                errors.append(f"{location}: 非法 category {category!r}")
            if not isinstance(item.get("source"), str) or not item["source"]:
                errors.append(f"{location}: 缺少 source")
            if not isinstance(item.get("license"), str) or not item["license"]:
                errors.append(f"{location}: 缺少 license")
            if item.get("reviewed") is not True:
                errors.append(f"{location}: reviewed 必须为 true 才可训练")
            digest = hashlib.sha256(
                json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            if digest in seen:
                message = f"{location}: 与 {seen[digest]} 内容重复"
                if reject_duplicates:
                    errors.append(message)
            else:
                seen[digest] = location

    print(f"校验 {len(paths)} 个文件，{total} 条样本，错误 {len(errors)}")
    for error in errors[:100]:
        print(f"  ✗ {error}", file=sys.stderr)
    if errors:
        print("校验失败", file=sys.stderr)
        return 1
    print("校验通过")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--reject-duplicates",
        action="store_true",
        help="内容重复的样本视为错误（否则仅提示）",
    )
    return validate(parser.parse_args().paths, parser.parse_args().reject_duplicates)


if __name__ == "__main__":
    raise SystemExit(main())
