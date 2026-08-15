"""channels.onebot: OneBot 11 私有消息适配。"""

from whitenight.channels.onebot.adapter import EventDeduplicator, OneBotAdapter, RateLimiter
from whitenight.channels.onebot.sender import OneBotSender, OneBotSendError, split_text
from whitenight.channels.onebot.session_map import ChannelSessionStore

__all__ = [
    "ChannelSessionStore",
    "EventDeduplicator",
    "OneBotAdapter",
    "OneBotSendError",
    "OneBotSender",
    "RateLimiter",
    "split_text",
]
