"""Deterministic approval commands shared by trusted chat channels."""

import re
from dataclasses import dataclass

_COMMAND = re.compile(
    r"^(?:(全部|全都)\s*)?(同意|批准|允许操作|允许|拒绝|不同意)"
    r"\s*([A-Za-z0-9_-]{6,16})?\s*[！!。.]?$"
)
_STATUS = re.compile(
    r"^(?:完成了吗|完成了没|移动好了吗|移好了吗|好了吗|现在什么状态|进度如何)[？?！!。\s]*$"
)


@dataclass(frozen=True)
class ApprovalCommand:
    allow: bool
    all_pending: bool
    code: str | None


def parse_approval_command(text: str) -> ApprovalCommand | None:
    match = _COMMAND.fullmatch(text.strip())
    if match is None or (match[1] and match[3]):
        return None
    return ApprovalCommand(match[2] not in {"拒绝", "不同意"}, bool(match[1]), match[3])


def is_operation_status(text: str) -> bool:
    return _STATUS.fullmatch(text.strip()) is not None
