from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, Application

from bot.handlers.discussion_forward_tracker_handler import discussion_forward_handler, forward_tracker
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


async def update_commands_for_all(bot: ContextTypes.DEFAULT_TYPE.bot) -> None:
    """
    Defines commands for all users and admins

    :param bot: telegram bot
    :return: None"""
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


def init_bot() -> Application:
    """
    Bot init function

    :return: None
    """
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    setup_handlers(application)
    application.add_handler(MessageHandler(
        (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP) & filters.IS_AUTOMATIC_FORWARD,
        discussion_forward_handler
    ))
    application.add_handler(CommandHandler("delete_my_data", delete_all_handler))

    application.add_error_handler(error_handler)

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

    application.job_queue.run_repeating(
        lambda ctx: forward_tracker.cleanup_expired(),
        interval=60
    )

    # Инициализация команд при старте
    async def post_init(app):
        await update_commands_for_all(app.bot)

    application.post_init = post_init

    return application