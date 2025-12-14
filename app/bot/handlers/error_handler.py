from telegram.ext import ContextTypes

from utils.logger import logger


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    Error handler of telegram bot

    :param update: telegram update
    :param context: telegram context
    :return: None
    """
    logger.error(f"Error: {context.error}")