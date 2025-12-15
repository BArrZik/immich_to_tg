from telegram import Update
from telegram.ext import ConversationHandler, ContextTypes

from bot.handlers.setup_handlers.setup_handler_consts import CHANNEL_NAME, IMMICH_HOST, API_KEY, ALBUM_UUID
from postgres.database import SessionLocal
from postgres.models import User, Channel, ApiKey, ImmichHost, Album
from utils.logger import logger


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Operate dialogue flow based on state.

    :param update: telegram update
    :param context: telegram bot context
    :return: state of dialogue
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == update.effective_user.id, User.deleted_at.is_(None)).first()

        if not user:
            user = User(telegram_id=update.effective_user.id, username=update.effective_user.username)
            db.add(user)
            db.commit()

        # Проверяем наличие активных каналов
        has_channels = (
            db.query(Channel).filter(Channel.user_id == user.user_id, Channel.deleted_at.is_(None)).first() is not None
        )

        if not has_channels:
            await update.message.reply_text("Введите имя вашего канала:")
            return CHANNEL_NAME

        # Проверяем наличие активных хостов Immich
        has_immich_hosts = (
            db.query(ImmichHost).filter(ImmichHost.user_id == user.user_id, ImmichHost.deleted_at.is_(None)).first()
            is not None
        )

        if not has_immich_hosts:
            await update.message.reply_text("Введите URL Immich сервера:")
            return IMMICH_HOST

        # Проверяем наличие активных API ключей
        has_api_keys = (
            db.query(ApiKey).filter(ApiKey.user_id == user.user_id, ApiKey.deleted_at.is_(None)).first() is not None
        )

        if not has_api_keys:
            await update.message.reply_text("Введите API ключ Immich:")
            return API_KEY

        # Проверяем наличие активных альбомов
        has_albums = (
            db.query(Album).filter(Album.user_id == user.user_id, Album.deleted_at.is_(None)).first() is not None
        )

        if not has_albums:
            await update.message.reply_text("Введите ID альбома в Immich:")
            return ALBUM_UUID

        await update.message.reply_text("Все данные заполнены! Бот готов к работе.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in start_handler: {str(e)}")
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте снова.")
        return ConversationHandler.END
    finally:
        db.close()
