from typing import Any, Coroutine

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.handlers.setup_handlers.setup_handler_consts import *
from postgres.database import SessionLocal
from postgres.models import User, Channel
from utils.logger import logger


async def channel_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None | int:
    """
    Process channel name and add it to db. Change dialogue state for start handlers

    :param update: telegram update
    :param context: telegram bot context
    :return: state of dialogue
    """
    db = SessionLocal()
    try:
        channel_name = update.message.text.strip().replace('@', '')
        channel_name = channel_name.split("/")[-1]
        user = db.query(User).filter(
            User.telegram_id == update.effective_user.id,
            User.deleted_at.is_(None)
        ).first()

        if not user:
            await update.message.reply_text("Ошибка: пользователь не найден. Начните с /start")
            return ConversationHandler.END

        # Пытаемся получить информацию о канале через Telegram API
        try:
            chat = await context.bot.get_chat(f"@{channel_name}")
            telegram_channel_id = chat.id

            # Проверяем, что бот админ в канале
            admins = await context.bot.get_chat_administrators(chat.id)
            if not any(admin.user.id == context.bot.id for admin in admins):
                await update.message.reply_text(
                    "Ошибка: бот должен быть администратором канала.\n"
                    "Добавьте бота как администратора и попробуйте снова:"
                )
                return CHANNEL_NAME

        except Exception as e:
            logger.error(f"Error getting channel info: {str(e)}")
            await update.message.reply_text(
                "Не удалось получить информацию о канале.\n"
                "Проверьте правильность имени и что бот добавлен в канал.\n"
                "Введите имя канала еще раз:"
            )
            return CHANNEL_NAME

        # Проверяем, есть ли уже такой канал у пользователя
        existing_channel = db.query(Channel).filter(
            Channel.user_id == user.user_id,
            Channel.telegram_channel_id == telegram_channel_id,
            Channel.deleted_at.is_(None)
        ).first()

        if existing_channel:
            # Обновляем существующий канал
            existing_channel.channel_name = channel_name
            existing_channel.channel_url = f"https://t.me/{channel_name}"
            existing_channel.deleted_at = None
        else:
            # Создаем новый канал
            channel = Channel(
                user_id=user.user_id,
                telegram_channel_id=telegram_channel_id,
                channel_name=channel_name,
                channel_url=f"https://t.me/{channel_name}"
            )
            db.add(channel)

        db.commit()

        await update.message.reply_text(
            f"Канал '{channel_name}' успешно привязан!\n"
            "Теперь введите URL Immich сервера:"
        )
        return IMMICH_HOST

    except Exception as e:
        logger.error(f"Error in channel_name_handler: {str(e)}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, введите имя канала еще раз:"
        )
        return CHANNEL_NAME
    finally:
        db.close()
