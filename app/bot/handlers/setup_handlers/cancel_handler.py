from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Cancel dialogue. Change dialogue state for start handlers

    :param update: telegram update
    :param context: telegram bot context
    :return: state of dialogue
    """
    await update.message.reply_text("Настройка отменена")
    return ConversationHandler.END
