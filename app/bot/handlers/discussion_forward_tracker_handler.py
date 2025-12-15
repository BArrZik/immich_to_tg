import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import logger


class DiscussionForwardTracker:
    """Mapping tracker channel_message_id → discussion_message_id"""

    def __init__(self, ttl_seconds: int = 300):
        self._mapping: Dict[Tuple[int, int], Tuple[int, datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)
        self._waiters: Dict[Tuple[int, int], asyncio.Event] = defaultdict(asyncio.Event)

    async def store(self, channel_id: int, channel_msg_id: int, discussion_msg_id: int) -> None:
        """
        Store mapping

        :param channel_id: initial channel id
        :param channel_msg_id: initial message id
        :param discussion_msg_id: discussion message id of forwarded message
        :return: None
        """
        key = (channel_id, channel_msg_id)
        self._mapping[key] = (discussion_msg_id, datetime.now())
        # Уведомить ожидающих
        if key in self._waiters:
            self._waiters[key].set()

    async def get(self, channel_id: int, channel_msg_id: int, timeout: float = 5.0) -> Optional[int]:
        """
        Get discussion_msg_id with timeout

        :param channel_id: initial channel id
        :param channel_msg_id: initial message id
        :param timeout: discussion message timeout
        :return: discussion message id
        """

        logger.debug(f"Getting cache for key {channel_id}, {channel_msg_id}")
        key = (channel_id, channel_msg_id)

        # Проверить кэш
        if key in self._mapping:
            msg_id, ts = self._mapping[key]
            if datetime.now() - ts < self._ttl:
                return msg_id

        # Ждать появления
        try:
            await asyncio.wait_for(self._waiters[key].wait(), timeout)
            if key in self._mapping:
                return self._mapping[key][0]
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for discussion message: {key}")

        return None

    async def cleanup_expired(self):
        """
        Delete expired discussion messages

        :return: None"""
        now = datetime.now()
        expired = [k for k, (_, ts) in self._mapping.items() if now - ts > self._ttl]
        for k in expired:
            del self._mapping[k]
            self._waiters.pop(k, None)


# Глобальный экземпляр
forward_tracker = DiscussionForwardTracker()


async def discussion_forward_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Forward handler of channels` messages in groups/supergroups

    :param update: telegram update
    :param context: telegram context
    :return: None
    """
    logger.debug(f"Tracked forward started for: {update.message}")
    message = update.message
    if not message or not message.is_automatic_forward:
        return

    # forward_origin содержит информацию об оригинальном сообщении
    if message.forward_origin and hasattr(message.forward_origin, "chat"):
        channel_id = message.forward_origin.chat.id
        channel_msg_id = getattr(message.forward_origin, "message_id")
        discussion_msg_id = message.message_id

        await forward_tracker.store(channel_id, channel_msg_id, discussion_msg_id)
        logger.debug(f"Tracked forward: channel {channel_id} msg {channel_msg_id} -> discussion msg {discussion_msg_id}")
