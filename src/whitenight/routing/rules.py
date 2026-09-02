"""确定性路由规则：规则优先于模型输出，用户指定在权限允许范围内服从。

规则设计保持高精度：宁可留在 WhiteNight 本地处理，也不把普通聊天误派给
外部 Agent（外部委派会扩大数据暴露面并消耗费用）。
"""

from __future__ import annotations

import re

from whitenight.policy.risk import RiskLevel
from whitenight.routing.models import (
    ExecutorChoice,
    RoutingPlan,
    TaskCategory,
)

_HERMES_PATTERN = re.compile(r"(?:用|交给|让|请)\s*(?:hermes|赫耳墨斯|电脑操作)", re.I)
_CODEX_COMMAND_PATTERN = re.compile(r"^\s*/codex(?:\s+(?P<prompt>.*))?\s*$", re.I | re.S)
_WHITENIGHT_PATTERN = re.compile(r"(?:小白|你自己|本地模型)\s*(?:来处理|自己来|处理|回答)")

_CODE_PATTERNS = [
    re.compile(r"(?:代码|程序|脚本|函数|模块|接口)"),
    re.compile(r"(?:编译|构建|报错|bug|调试|debug|重构|单元测试|集成测试)"),
    re.compile(r"(?:实现|编写|写)(?:一个|个)?(?:函数|脚本|程序|类|模块|测试)"),
    re.compile(r"(?:git\s+(?:commit|push|branch|diff)|修.*测试|跑.*测试)"),
]

_GUI_PATTERNS = [
    re.compile(
        r"(?:打开|启动|关闭|切换)\s*(?:应用|app|程序|浏览器|窗口|文件管理器|Safari|Chrome|Finder|访达|微信|QQ)"
    ),
    re.compile(r"(?:点击|勾选|拖拽|填表|跨应用|操作电脑|桌面操作|自动化操作)"),
    re.compile(r"(?:先.+再.+然后|依次.+再.+最后).{0,60}"),
]

_SEARCH_PATTERN = re.compile(r"(?:搜索|查一下|上网查|检索|找一下)")
_MEMORY_PATTERN = re.compile(r"(?:记得|回忆|记忆|之前说|我告诉过你|你存过)")
_FILE_PATTERN = re.compile(r"(?:读取|查看|打开|新建|创建|修改|移动|删除)\s*(?:这个|一下|文件|文档)")


def _has_any(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


class RuleRouter:
    """高精度规则路由；返回 None 表示留给 LLM 路由/默认本地处理。"""

    def __init__(self, allow_hermes: bool = False) -> None:
        self._allow_hermes = allow_hermes

    @property
    def allow_hermes(self) -> bool:
        return self._allow_hermes

    def route(self, text: str, has_image: bool = False) -> RoutingPlan | None:
        text = text.strip()
        if not text and not has_image:
            return RoutingPlan(
                category=TaskCategory.CHAT,
                executor=ExecutorChoice.WHITENIGHT,
                risk=RiskLevel.READ_ONLY,
                confidence=1.0,
                reason="空消息留在本地聊天",
            )

        # Hermes is opt-in; when disabled, direct requests remain with WhiteNight.
        if _HERMES_PATTERN.search(text) and not self._allow_hermes:
            return RoutingPlan(
                category=TaskCategory.GUI,
                executor=ExecutorChoice.WHITENIGHT,
                risk=RiskLevel.MEDIUM,
                confidence=0.98,
                reason="Hermes 暂时禁用，由小白本体处理电脑操作请求",
            )
        if _HERMES_PATTERN.search(text) and self._allow_hermes:
            return RoutingPlan(
                category=TaskCategory.GUI,
                executor=ExecutorChoice.HERMES,
                risk=RiskLevel.MEDIUM,
                confidence=0.98,
                reason="用户指定 Hermes",
                user_override=True,
            )
        if _CODEX_COMMAND_PATTERN.match(text):
            return RoutingPlan(
                category=TaskCategory.CODE,
                executor=ExecutorChoice.CODEX,
                risk=RiskLevel.HIGH,
                confidence=0.98,
                reason="用户指定 Codex",
                user_override=True,
            )
        if _WHITENIGHT_PATTERN.search(text):
            return RoutingPlan(
                category=TaskCategory.CHAT,
                executor=ExecutorChoice.WHITENIGHT,
                risk=RiskLevel.READ_ONLY,
                confidence=0.98,
                reason="用户指定小白本地处理",
                user_override=True,
            )

        if has_image and len(text) <= 400:
            return RoutingPlan(
                category=TaskCategory.IMAGE_QA,
                executor=ExecutorChoice.WHITENIGHT,
                risk=RiskLevel.READ_ONLY,
                confidence=0.95,
                reason="图片问答由本地视觉模型处理",
            )

        if _has_any(text, _CODE_PATTERNS):
            return RoutingPlan(
                category=TaskCategory.CODE,
                executor=ExecutorChoice.WHITENIGHT,
                risk=RiskLevel.HIGH,
                confidence=0.9,
                reason="命中编码/软件工程任务规则，由小白本体处理；Codex 需使用 /codex",
                expected_artifacts=["代码变更", "测试结果"],
            )

        if _has_any(text, _GUI_PATTERNS):
            return RoutingPlan(
                category=TaskCategory.GUI,
                executor=ExecutorChoice.HERMES if self._allow_hermes else ExecutorChoice.WHITENIGHT,
                risk=RiskLevel.MEDIUM,
                confidence=0.88,
                reason=(
                    "命中 GUI/跨应用操作规则"
                    if self._allow_hermes
                    else "命中 GUI/跨应用操作规则；Hermes 暂时禁用，由小白本体处理"
                ),
            )

        if _MEMORY_PATTERN.search(text):
            return RoutingPlan(
                category=TaskCategory.MEMORY,
                executor=ExecutorChoice.WHITENIGHT,
                risk=RiskLevel.READ_ONLY,
                confidence=0.9,
                reason="命中记忆查询规则",
            )

        if _SEARCH_PATTERN.search(text):
            return RoutingPlan(
                category=TaskCategory.SEARCH,
                executor=ExecutorChoice.WHITENIGHT,
                risk=RiskLevel.READ_ONLY,
                confidence=0.9,
                reason="命中联网搜索规则",
            )

        if _FILE_PATTERN.search(text):
            return RoutingPlan(
                category=TaskCategory.FILE_OP,
                executor=ExecutorChoice.WHITENIGHT,
                risk=RiskLevel.READ_ONLY,
                confidence=0.85,
                reason="命中轻量文件操作规则",
            )

        # 默认：陪伴/闲聊全部留在本地，不外发。
        category = TaskCategory.COMPANIONSHIP
        return RoutingPlan(
            category=category,
            executor=ExecutorChoice.WHITENIGHT,
            risk=RiskLevel.READ_ONLY,
            confidence=0.8,
            reason="默认本地处理（陪伴/闲聊）",
        )


def extract_codex_prompt(text: str) -> str | None:
    """Return the task body for a leading ``/codex`` command."""
    match = _CODEX_COMMAND_PATTERN.match(text)
    if match is None:
        return None
    return (match.group("prompt") or "").strip()
