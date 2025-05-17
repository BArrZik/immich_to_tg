from utils.logger import logger
from bot.bot_client import init_bot


def main():
    bot = init_bot()
    bot.run_polling()

if __name__ == "__main__":
    logger.info("main started")
    main()