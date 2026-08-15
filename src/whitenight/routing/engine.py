"""路由引擎：规则优先 → 可选 LLM 结构化输出 → 本地兜底。

失败升级：本地工具连续失败允许升级 Hermes；任何委派都不降低审批等级。
"""

from __future__ import annotations

import json
import logging
import re

from whitenight.models.base import ModelProvider, ProviderMessage
from whitenight.policy.risk import RiskLevel
from whitenight.routing.models import (
    ExecutorChoice,
    RoutingPlan,
    TaskCategory,
)
from whitenight.routing.rules import RuleRouter

logger = logging.getLogger(__name__)


class RoutingError(RuntimeError):
    """路由输出无法解析。"""


class OllamaRoutingRouter:
    """结构化路由输出；严格 Schema 解析失败返回 None（规则/兜底接管）。"""

    _PROMPT = (
        "把用户消息分类。只输出 JSON，字段：category（chat/companionship/"
        "image_qa/memory/search/file_op/gui/code）、executor（whitenight/"
        "hermes/codex）、risk（read_only/low_write/medium/high）、"
        "confidence（0-1）、reason。编码类用 codex；GUI/跨应用用 hermes；"
        "其余用 whitenight。\n"
    )

    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    async def route(self, text: str, has_image: bool = False) -> RoutingPlan | None:
        prompt = self._PROMPT + f"has_image={has_image}\n用户消息：{text}"
        try:
            chunks = self._provider.stream_chat([ProviderMessage(role="user", content=prompt)])
            parts: list[str] = []
            async for chunk in chunks:
                if chunk.delta:
                    parts.append(chunk.delta)
                if chunk.done:
                    break
            raw = "".join(parts)
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                return None
            payload = json.loads(match.group(0))
            return RoutingPlan.model_validate(payload)
        except Exception as exc:
            logger.warning("LLM 路由失败，回退规则/本地：%s", exc)
            return None


class RoutingEngine:
    """WhiteNight 任务分类与委派决策。"""

    def __init__(
        self,
        rule_router: RuleRouter | None = None,
        llm_router: OllamaRoutingRouter | None = None,
        allow_llm_fallback: bool = True,
    ) -> None:
        self._rules = rule_router or RuleRouter()
        self._llm = llm_router
        self._allow_llm_fallback = allow_llm_fallback

    async def route(
        self, text: str, has_image: bool = False, user_override: str | None = None
    ) -> RoutingPlan:
        # 规则层最先、也最可靠；黄金路由集只依赖规则层。
        plan = self._rules.route(text, has_image=has_image)
        if plan is None and self._allow_llm_fallback and self._llm is not None:
            plan = await self._llm.route(text, has_image=has_image)

        if plan is None:
            plan = RoutingPlan(
                category=TaskCategory.CHAT,
                executor=ExecutorChoice.WHITENIGHT,
                risk=RiskLevel.READ_ONLY,
                confidence=0.5,
                reason="路由兜底：本地处理",
            )

        if user_override:
            override = user_override.strip().lower()
            if override in {"hermes", "codex"}:
                plan = RoutingPlan(
                    category=TaskCategory.GUI if override == "hermes" else TaskCategory.CODE,
                    executor=ExecutorChoice(override),
                    risk=RiskLevel.MEDIUM if override == "hermes" else RiskLevel.HIGH,
                    confidence=1.0,
                    reason=f"显式指定 {override}（权限允许范围内服从）",
                    user_override=True,
                )
        return plan
