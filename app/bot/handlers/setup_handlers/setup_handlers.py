from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, filters

from bot.handlers.setup_handlers.album_uuid_handler import album_uuid_handler
from bot.handlers.setup_handlers.api_key_handler import api_key_handler
from bot.handlers.setup_handlers.cancel_handler import cancel_handler
from bot.handlers.setup_handlers.channel_name_handler import channel_name_handler
from bot.handlers.setup_handlers.immich_host_handler import immich_host_handler
from bot.handlers.setup_handlers.setup_handler_consts import *
from bot.handlers.setup_handlers.start_handler import start_handler

def setup_handlers(application) -> None:
    """
    State machine for start handler

    :param application: telegram bot
    :return: None
    """
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_handler)],
        states={
            CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_name_handler)],
            IMMICH_HOST: [MessageHandler(filters.TEXT & ~filters.COMMAND, immich_host_handler)],
            API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, api_key_handler)],
            ALBUM_UUID: [MessageHandler(filters.TEXT & ~filters.COMMAND, album_uuid_handler)]
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)]
    )

    application.add_handler(conv_handler)