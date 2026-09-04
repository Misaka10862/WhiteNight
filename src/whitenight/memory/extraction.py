"""记忆提取：主回复后异步执行，不阻塞聊天。

Provider 失败时返回空结果并记录日志；绝不把模型输出直接当作事实写入，
所有候选都带来源消息与置信度。
"""

from __future__ import annotations

import json
import logging
import re
from typing import ClassVar, Protocol

from whitenight.channels.types import MessageRecord
from whitenight.memory.types import EpisodeCandidate, ExtractionResult, FactCandidate
from whitenight.models.base import ModelProvider, ProviderMessage

logger = logging.getLogger(__name__)


class MemoryExtractor(Protocol):
    async def extract(self, messages: list[MessageRecord]) -> ExtractionResult: ...


class RuleBasedMemoryExtractor:
    """确定性规则回退：覆盖最常用偏好表达，便于测试与离线运行。"""

    _PATTERNS: ClassVar[list[tuple[str, str]]] = [
        (r"(?:我是|我叫)\s*(.+)", "称呼"),
        (r"我喜欢\s*(.+)", "喜好"),
        (r"我住在\s*(.+)", "住处"),
        (r"我的生日是\s*(.+)", "生日"),
    ]

    async def extract(self, messages: list[MessageRecord]) -> ExtractionResult:
        facts: list[FactCandidate] = []
        episodes: list[EpisodeCandidate] = []
        for message in messages:
            if message.role != "user":
                continue
            text = message.content.strip()
            for pattern, key in self._PATTERNS:
                match = re.search(pattern, text)
                if match:
                    facts.append(
                        FactCandidate(
                            key=key,
                            value=match.group(1).strip()[:2000],
                            confidence=0.75,
                            source_message_ids=[message.id],
                        )
                    )
            if re.search(r"(纪念|第一次|承诺|生日|最重要|永远)", text):
                episodes.append(
                    EpisodeCandidate(
                        content=text[:4000],
                        confidence=0.7,
                        importance=0.7,
                        source_message_ids=[message.id],
                    )
                )
        return ExtractionResult(facts=facts, episodes=episodes)


class OllamaMemoryExtractor:
    """用本地模型提取候选；严格 Schema 解析失败则本次提取为空。"""

    _PROMPT = (
        "你是记忆提取器。只从对话中提取稳定事实和有价值的情景记忆。\n"
        "只输出 JSON，格式："
        '{"facts":[{"key":"称呼","value":"主人","confidence":0.9,'
        '"source_message_ids":["..."]}],'
        '"episodes":[{"content":"...","confidence":0.8,"importance":0.7,'
        '"source_message_ids":["..."]}]}\n'
        "不要输出 JSON 以外的内容。没有可提取内容时输出空数组。"
    )

    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    def set_provider(self, provider: ModelProvider) -> None:
        """Replace the provider used by future extraction requests."""
        self._provider = provider

    async def extract(self, messages: list[MessageRecord]) -> ExtractionResult:
        transcript = "\n".join(
            f"{message.id} [{message.role}] {message.content}" for message in messages[-20:]
        )
        try:
            chunks = self._provider.stream_chat(
                [
                    ProviderMessage(role="system", content=self._PROMPT),
                    ProviderMessage(role="user", content=transcript),
                ]
            )
            text_parts: list[str] = []
            completed = False
            async for chunk in chunks:
                if chunk.delta:
                    text_parts.append(chunk.delta)
                if chunk.done:
                    completed = True
                    break
            raw = "".join(text_parts)
            if not completed:
                return ExtractionResult(succeeded=False)
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                logger.warning("记忆提取没有 JSON 输出 chars=%s", len(raw))
                return ExtractionResult(succeeded=False)
            payload = json.loads(match.group(0))
            return ExtractionResult.model_validate(payload)
        except Exception as exc:  # 记忆提取失败不阻塞聊天
            logger.warning("记忆提取失败 error_type=%s", type(exc).__name__)
            return ExtractionResult(succeeded=False)


class NullMemoryExtractor:
    async def extract(self, messages: list[MessageRecord]) -> ExtractionResult:
        del messages
        return ExtractionResult()
