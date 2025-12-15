from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.handlers.setup_handlers.setup_handler_consts import IMMICH_HOST, API_KEY
from immich.immich_client import ImmichClient
from postgres.database import SessionLocal
from postgres.models import User, ImmichHost
from utils.logger import logger


async def immich_host_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None | int:
    """
    Process immich host and add it to db. Change dialogue state for start handlers

    :param update: telegram update
    :param context: telegram bot context
    :return: state of dialogue
    """
    db = SessionLocal()
    try:
        host_url = update.message.text.strip()

        # Validate URL and port
        if ":" in host_url and not any(c.isdigit() for c in host_url.split(":")[-1]):
            await update.message.reply_text("Порт должен быть числовым. Пожалуйста, введите URL в формате host:port")
            return IMMICH_HOST

        normalized_url = ImmichClient.normalize_url(host_url)

        user = db.query(User).filter(User.telegram_id == update.effective_user.id, User.deleted_at.is_(None)).first()

        if not user:
            await update.message.reply_text("Ошибка: пользователь не найден. Начните с /start")
            return ConversationHandler.END

        # Check is there any active host for user
        existing_host = (
            db.query(ImmichHost).filter(ImmichHost.user_id == user.user_id, ImmichHost.deleted_at.is_(None)).first()
        )

        if existing_host:
            existing_host.host_url = normalized_url
            existing_host.deleted_at = None
            db.commit()
            await update.message.reply_text(f"URL сервера обновлен: {normalized_url}\nТеперь введите API ключ Immich:")
        else:
            immich_host = ImmichHost(user_id=user.user_id, host_url=normalized_url)
            db.add(immich_host)
            db.commit()
            await update.message.reply_text(f"URL сервера сохранен: {normalized_url}\nТеперь введите API ключ Immich:")

        return API_KEY
    except Exception as e:
        logger.error(f"Error in immich_host_handler: {str(e)}")
        await update.message.reply_text(f"Ошибка: {str(e)}\nПожалуйста, введите правильный URL Immich сервера:")
        return IMMICH_HOST
    finally:
        db.close()
