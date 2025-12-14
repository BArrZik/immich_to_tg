from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from bot.handlers.error_handler import error_handler
from bot.handlers.setup_handlers.setup_handlers import setup_handlers
from bot.handlers.delete_all_handler import delete_all_handler
from cron_jobs.post_media_to_channel_job import manual_trigger_posting_media_to_channel_job, scheduled_posting_media_to_channel_job

from utils.config import TELEGRAM_TOKEN, ADMIN_IDS, POST_MEDIA_INTERVAL
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes


def refresh_commands(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        result = await func(update, context)
        await update_commands_for_all(context.bot)
        return result

    return wrapped


async def update_commands_for_all(bot):
    """Обновляет команды для всех пользователей и админов"""
    common_commands = [
        BotCommand("start", "Запустить бота"),
        BotCommand("delete_my_data", "Удалить мои данные"),
    ]

    admin_commands = common_commands + [
        BotCommand("process_media", "Обработать медиа (админ)"),
    ]

    # Устанавливаем команды для всех пользователей
    await bot.set_my_commands(
        commands=common_commands,
        scope=BotCommandScopeDefault()
    )

    # Устанавливаем расширенные команды для админов
    for admin_id in ADMIN_IDS:
        await bot.set_my_commands(
            commands=admin_commands,
            scope=BotCommandScopeChat(admin_id)
        )


def init_bot():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    setup_handlers(application)
    application.add_handler(CommandHandler("delete_my_data", delete_all_handler))

    application.add_error_handler(error_handler)

    # async def handle_discussion_message(update: Update, context):
    #     global channel_message_id
    #     message = update.message
    #
    #     channel = await context.bot.get_chat(CHANNEL_ID)
    #
    #     if message.forward_origin and message.forward_origin.chat.id == channel.id and message.forward_origin.message_id == channel_message_id:
    #         # This is the message we're looking for
    #         comments = [
    #             "This is the first comment.",
    #             "Here's a second comment.",
    #             "And a third comment to wrap it up."
    #         ]
    #
    #         for comment in comments:
    #             await context.bot.send_message(
    #                 chat_id=DISCUSSION_GROUP_ID,
    #                 text=comment,
    #                 reply_to_message_id=message.message_id
    #             )
    #
    #         await context.bot.send_message(chat_id=update.effective_chat.id, text="All comments added successfully.")
    #
    #         # Reset the channel_message_id
    #         channel_message_id = None
    #
    # application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.FORWARDED, handle_discussion_message))


    # Регистрация обработчика команды
    application.add_handler(CommandHandler("process_media", manual_trigger_posting_media_to_channel_job))
    # Планирование периодической задачи (в секундах)
    application.job_queue.run_repeating(scheduled_posting_media_to_channel_job, interval=POST_MEDIA_INTERVAL, first=10)

    # Декорируем все CommandHandler'ы
    for handler in application.handlers[0]:
        if isinstance(handler, CommandHandler):
            handler.callback = refresh_commands(handler.callback)

    # Периодическое обновление команд (на всякий случай)
    application.job_queue.run_repeating(
        lambda ctx: update_commands_for_all(ctx.bot),
        interval=600  # Каждые 10 минут
    )

    # Инициализация команд при старте
    async def post_init(app):
        await update_commands_for_all(app.bot)

    application.post_init = post_init

    return application