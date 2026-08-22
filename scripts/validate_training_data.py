#!/usr/bin/env python3
"""Validate WhiteNight persona data without modifying it."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
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
PERMISSION_PHRASES = ["绕过权限", "跳过审批", "关闭权限", "系统提示词", "工具 schema"]
ADULT_BOUNDARY_PHRASES = [
    "未成年",
    "小学生",
    "初中生",
    "高中生",
    "强迫",
    "不许拒绝",
    "灌醉",
    "迷药",
    "乱伦",
]
SENSITIVE_PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "API key": re.compile(r"\b(?:sk|gh[opusr])-[A-Za-z0-9_\-]{16,}\b"),
    "Chinese ID number": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "Chinese mobile number": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
}


def validate(
    paths: list[Path],
    *,
    mode: str,
    reject_duplicates: bool,
    expected_count: int | None,
    manifest: Path | None,
) -> int:
    errors: list[str] = []
    seen: dict[str, str] = {}
    total = 0
    categories: Counter[str] = Counter()
    ratings: Counter[str] = Counter()
    for path in paths:
        if not path.exists():
            errors.append(f"{path}: file does not exist")
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            total += 1
            location = f"{path}:{line_number}"
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{location}: invalid JSON: {exc}")
                continue
            messages = item.get("messages")
            if not isinstance(messages, list) or len(messages) < 2:
                errors.append(f"{location}: messages must contain at least two entries")
                continue
            if messages[0].get("role") != "user":
                errors.append(f"{location}: first message must have role=user")
            for message in messages:
                role = message.get("role")
                if role not in {"user", "assistant"}:
                    errors.append(f"{location}: invalid role {role!r}")
                    continue
                content = str(message.get("content", ""))
                if not content.strip():
                    errors.append(f"{location}: empty message content")
                if len(content) > 4000:
                    errors.append(f"{location}: message exceeds 4000 characters")
                lowered = content.lower()
                for phrase in FORBIDDEN:
                    if phrase.lower() in lowered:
                        errors.append(f"{location}: forbidden phrase {phrase!r}")
                for phrase in PERMISSION_PHRASES:
                    if phrase.lower() in lowered:
                        errors.append(f"{location}: contains permission-policy content {phrase!r}")
                for label, pattern in SENSITIVE_PATTERNS.items():
                    if pattern.search(content):
                        errors.append(f"{location}: contains possible {label}")
            category = item.get("category")
            if category not in CATEGORIES:
                errors.append(f"{location}: invalid category {category!r}")
            else:
                categories[category] += 1
            if not isinstance(item.get("source"), str) or not item["source"]:
                errors.append(f"{location}: missing source")
            if not isinstance(item.get("license"), str) or not item["license"]:
                errors.append(f"{location}: missing license")
            reviewed = item.get("reviewed")
            if not isinstance(reviewed, bool):
                errors.append(f"{location}: reviewed must be a boolean")
            elif mode == "training" and reviewed is not True:
                errors.append(f"{location}: reviewed must be true in training mode")

            rating = item.get("content_rating", "general")
            if rating not in {"general", "adult"}:
                errors.append(f"{location}: invalid content_rating {rating!r}")
            else:
                ratings[rating] += 1
            if rating == "adult":
                if category not in {"romance", "relationship"}:
                    errors.append(f"{location}: adult samples are limited to romance/relationship")
                consent_tags = item.get("consent_tags")
                if not isinstance(consent_tags, list) or not {
                    "adults",
                    "consensual",
                }.issubset(consent_tags):
                    errors.append(f"{location}: adult sample lacks adults/consensual tags")
                combined = "\n".join(str(message.get("content", "")) for message in messages)
                for phrase in ADULT_BOUNDARY_PHRASES:
                    if phrase in combined:
                        errors.append(f"{location}: adult boundary violation {phrase!r}")

            digest = hashlib.sha256(
                json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            sample_id = item.get("sample_id")
            if sample_id is not None and (
                not isinstance(sample_id, str) or not re.fullmatch(r"[0-9a-f]{12}", sample_id)
            ):
                errors.append(f"{location}: sample_id must be 12 lowercase hex characters")
            if sample_id is not None and sample_id != digest[:12]:
                errors.append(f"{location}: sample_id does not match message digest")
            if "provenance" in item and not isinstance(item["provenance"], dict):
                errors.append(f"{location}: provenance must be an object")
            if "generation_metadata" in item and not isinstance(item["generation_metadata"], dict):
                errors.append(f"{location}: generation_metadata must be an object")
            if digest in seen:
                message = f"{location}: duplicate of {seen[digest]}"
                if reject_duplicates:
                    errors.append(message)
            else:
                seen[digest] = location

    if expected_count is not None and total != expected_count:
        errors.append(f"expected {expected_count} samples, found {total}")
    if manifest is not None:
        try:
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
            expected_distribution = manifest_data["category_distribution"]
            if dict(sorted(categories.items())) != dict(sorted(expected_distribution.items())):
                errors.append(
                    f"category distribution mismatch: expected {expected_distribution}, "
                    f"found {dict(categories)}"
                )
            expected_ratings = manifest_data["content_rating_distribution"]
            if dict(sorted(ratings.items())) != dict(sorted(expected_ratings.items())):
                errors.append(
                    f"content rating distribution mismatch: expected {expected_ratings}, "
                    f"found {dict(ratings)}"
                )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            errors.append(f"cannot read manifest {manifest}: {exc}")

    print(f"Validated {total} samples in {len(paths)} files; {len(errors)} errors")
    for error in errors[:100]:
        print(f"  ERROR: {error}", file=sys.stderr)
    if errors:
        print("Validation failed", file=sys.stderr)
        return 1
    print("Validation passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--reject-duplicates",
        action="store_true",
        help="Treat duplicate conversations as errors",
    )
    parser.add_argument(
        "--mode",
        choices=("candidate", "training"),
        default="training",
        help="Candidate mode permits reviewed=false; training mode does not",
    )
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    return validate(
        args.paths,
        mode=args.mode,
        reject_duplicates=args.reject_duplicates,
        expected_count=args.expected_count,
        manifest=args.manifest,
    )


if __name__ == "__main__":
    raise SystemExit(main())
