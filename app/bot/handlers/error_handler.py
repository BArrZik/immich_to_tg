from telegram.ext import ContextTypes

from utils.logger import logger


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")