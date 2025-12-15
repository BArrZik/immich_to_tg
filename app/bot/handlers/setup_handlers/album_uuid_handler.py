from datetime import datetime

import httpx
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.handlers.setup_handlers.setup_handler_consts import ALBUM_UUID
from cron_jobs.post_media_to_channel_job import media_jobs
from postgres.database import SessionLocal
from postgres.models import User, Album
from utils.logger import logger


async def album_uuid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Process album uuid from Immich and add it to db. Change dialogue state for start handlers

    :param update: telegram update
    :param context: telegram bot context
    :return: state of dialogue
    """
    db = SessionLocal()
    try:
        album_uuid = update.message.text.strip()
        user = db.query(User).filter(User.telegram_id == update.effective_user.id, User.deleted_at.is_(None)).first()

        if not user:
            await update.message.reply_text("Ошибка: пользователь не найден. Начните с /start")
            return ConversationHandler.END

        # Проверяем существование альбома и получаем его название
        try:
            album_info = await media_jobs.immich_service.get_user_album_info(user.telegram_id, album_uuid)
            if not album_info.get("assets"):
                await update.message.reply_text(
                    f"Альбом '{album_info.get('albumName', '')}' пуст. Добавьте фотографии в альбом и попробуйте снова:"
                )
                return ALBUM_UUID

            album_name = album_info.get("albumName", "без названия")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                await update.message.reply_text("Альбом не найден. Проверьте ID и попробуйте еще раз:")
            else:
                await update.message.reply_text(f"Ошибка сервера: {e.response.text}\nПопробуйте еще раз:")
            return ALBUM_UUID
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {str(e)}\nПопробуйте еще раз:")
            return ALBUM_UUID

        # Сохраняем альбом
        db.query(Album).filter(Album.user_id == user.user_id).update({"deleted_at": datetime.now()})

        new_album = Album(
            user_id=user.user_id,
            album_uuid=f"{album_uuid}",
        )
        db.add(new_album)
        db.commit()

        await update.message.reply_text(
            f"Альбом '{album_name}' успешно привязан!\n"
            f"Количество фотографий: {len(album_info['assets'])}\n"
            "Настройка завершена! Теперь вы можете использовать бота."
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error in album_id_handler: {str(e)}")
        await update.message.reply_text("Произошла ошибка. Попробуйте еще раз:")
        return ALBUM_UUID
    finally:
        db.close()
