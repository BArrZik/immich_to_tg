from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.handlers.setup_handlers.setup_handler_consts import ALBUM_UUID
from postgres.database import SessionLocal
from postgres.models import User, ApiKey


async def api_key_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Process api key for Immich and add it to db. Change dialogue state for start handlers

    :param update: telegram update
    :param context: telegram bot context
    :return: state of dialogue
    """
    db = SessionLocal()
    try:
        api_key = update.message.text.strip()
        user = db.query(User).filter(User.telegram_id == update.effective_user.id, User.deleted_at.is_(None)).first()

        if user:
            api_key_record = ApiKey(user_id=user.user_id, api_key=api_key)
            db.add(api_key_record)
            db.commit()
            await update.message.reply_text("Теперь введите ID альбома в Immich:")
            return ALBUM_UUID
        else:
            await update.message.reply_text("Ошибка: пользователь не найден. Начните с /start")
            return ConversationHandler.END
    finally:
        db.close()
