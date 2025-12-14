import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import logger


class DiscussionForwardTracker:
    """Трекер маппинга channel_message_id → discussion_message_id"""

    def __init__(self, ttl_seconds: int = 300):
        self._mapping: Dict[Tuple[int, int], Tuple[int, datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)
        self._waiters: Dict[Tuple[int, int], asyncio.Event] = defaultdict(asyncio.Event)

    def store(self, channel_id: int, channel_msg_id: int, discussion_msg_id: int):
        """Сохранить маппинг"""
        key = (channel_id, channel_msg_id)
        self._mapping[key] = (discussion_msg_id, datetime.now())
        # Уведомить ожидающих
        if key in self._waiters:
            self._waiters[key].set()

    async def get(self, channel_id: int, channel_msg_id: int,
                  timeout: float = 5.0) -> Optional[int]:
        """Получить discussion_msg_id с ожиданием"""
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

    def cleanup_expired(self):
        """Удалить устаревшие записи"""
        now = datetime.now()
        expired = [k for k, (_, ts) in self._mapping.items()
                   if now - ts > self._ttl]
        for k in expired:
            del self._mapping[k]
            self._waiters.pop(k, None)


# Глобальный экземпляр
forward_tracker = DiscussionForwardTracker()


async def discussion_forward_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик автоматических форвардов из каналов в группы обсуждений"""
    message = update.message
    if not message or not message.is_automatic_forward:
        return

    # forward_origin содержит информацию об оригинальном сообщении
    if message.forward_origin and hasattr(message.forward_origin, 'chat'):
        channel_id = message.forward_origin.chat.id
        channel_msg_id = message.forward_origin.message_id
        discussion_msg_id = message.message_id

        forward_tracker.store(channel_id, channel_msg_id, discussion_msg_id)
        logger.debug(f"Tracked forward: channel {channel_id} msg {channel_msg_id} → discussion msg {discussion_msg_id}")
