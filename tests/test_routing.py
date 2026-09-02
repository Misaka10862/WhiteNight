"""路由黄金集测试：规则层目标准确率 ≥ 0.9。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from whitenight.routing.engine import RoutingEngine
from whitenight.routing.rules import RuleRouter

GOLDEN = Path(__file__).resolve().parents[1] / "evals" / "routing" / "golden.jsonl"


def _load_golden() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def test_golden_routing_accuracy() -> None:
    router = RoutingEngine(rule_router=RuleRouter(), allow_llm_fallback=False)
    correct = 0
    failures: list[str] = []

    async def run() -> None:
        nonlocal correct
        for index, row in enumerate(_load_golden()):
            plan = await router.route(str(row["text"]), has_image=bool(row.get("has_image")))
            if plan.category.value == row["category"] and plan.executor.value == row["executor"]:
                correct += 1
            else:
                failures.append(
                    f"{index}: {row['text']!r} -> "
                    f"{plan.category.value}/{plan.executor.value} "
                    f"(期望 {row['category']}/{row['executor']})"
                )

    asyncio.run(run())
    total = len(_load_golden())
    accuracy = correct / total
    assert accuracy >= 0.9, "\n".join([f"accuracy={accuracy:.2f}", *failures])


def test_codex_override_still_requires_command() -> None:
    async def run() -> None:
        engine = RoutingEngine(rule_router=RuleRouter(), allow_llm_fallback=False)
        plan = await engine.route("帮我写个排序函数", user_override="hermes")
        assert plan.executor.value == "whitenight"
        plan = await engine.route("今天天气不错", user_override="codex")
        assert plan.executor.value == "whitenight"
        plan = await engine.route("/codex 写个排序函数", user_override="codex")
        assert plan.executor.value == "codex"

    asyncio.run(run())


def test_rule_router_basic_cases() -> None:
    router = RuleRouter()
    assert router.route("帮我写一个函数").executor.value == "whitenight"
    assert router.route("/codex 帮我写一个函数").executor.value == "codex"
    assert router.route("打开 Safari").executor.value == "whitenight"
    assert router.route("还记得我喜欢什么吗").executor.value == "whitenight"
    assert router.route("帮我搜索一下教程").executor.value == "whitenight"


def test_hermes_can_be_enabled_explicitly() -> None:
    router = RuleRouter(allow_hermes=True)
    assert router.route("打开 Safari").executor.value == "hermes"
