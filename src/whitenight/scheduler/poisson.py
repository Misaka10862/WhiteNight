"""泊松主动消息调度：默认频率约 1-2 次/天，不固定时间打卡。

时间约定：调度输入输出使用本机 local naive datetime（静默时段是墙上时间）；
数据库中的时间戳为 UTC（调用方负责转换）。
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, time, timedelta

from whitenight.scheduler.types import ProactiveConfig

_MAX_DRAWS = 256


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _in_quiet(local: datetime, config: ProactiveConfig) -> bool:
    start = parse_hhmm(config.quiet_start)
    end = parse_hhmm(config.quiet_end)
    current = local.time()
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def active_minutes_per_day(config: ProactiveConfig) -> float:
    start = parse_hhmm(config.quiet_start)
    end = parse_hhmm(config.quiet_end)
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    if start_minutes == end_minutes:
        return 24 * 60.0
    quiet = (
        end_minutes - start_minutes
        if end_minutes > start_minutes
        else 24 * 60 - start_minutes + end_minutes
    )
    return max(1.0, 24 * 60.0 - quiet)


def _next_quiet_end(local: datetime, config: ProactiveConfig) -> datetime:
    end = parse_hhmm(config.quiet_end)
    candidate = datetime.combine(local.date(), end)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def _exponential_minutes(rate_per_minute: float, rng: random.Random) -> float:
    u = max(rng.random(), 1e-9)
    return -math.log(1.0 - u) / rate_per_minute


def next_candidate(
    local_now: datetime,
    config: ProactiveConfig,
    last_activity_local: datetime | None = None,
    rng: random.Random | None = None,
) -> datetime:
    """生成下一个候选时间：指数间隔 + 静默时段 + 最近活动抑制。"""
    rng = rng or random.Random()
    rate = config.expected_per_day / active_minutes_per_day(config)
    candidate = local_now + timedelta(minutes=_exponential_minutes(rate, rng))
    if last_activity_local is not None:
        floor = last_activity_local + timedelta(minutes=config.suppress_minutes)
        candidate = max(candidate, floor)

    for _ in range(_MAX_DRAWS):
        if not _in_quiet(candidate, config):
            return candidate
        candidate = _next_quiet_end(candidate, config) + timedelta(
            minutes=_exponential_minutes(rate, rng)
        )
    return candidate + timedelta(minutes=config.suppress_minutes)


def utc_naive_to_local(value: datetime) -> datetime:
    """SQLite 中的 naive UTC → 本机 local naive。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone().replace(tzinfo=None)


def local_naive_to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)
