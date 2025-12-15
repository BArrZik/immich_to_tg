import subprocess
import sys

from utils.logger import logger
from bot.bot_client import init_bot


def run_migrations():
    """Выполняет команду миграции Alembic."""

    # Формируем команду
    command = ["alembic", "upgrade", "head"]

    logger.info(f"Running migrations command: {' '.join(command)}")

    try:
        # Выполняем команду
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        logger.info("Migrations applied successfully.")
        if result.stdout:
            logger.info(f"Alembic Output: {result.stdout.strip()}")

    except subprocess.CalledProcessError as e:
        logger.error(f"Alembic failed with error code {e.returncode}")
        logger.error(f"Alembic Stderr: {e.stderr.strip()}")
        # Если миграции не прошли, аварийно завершаем работу
        sys.exit(1)


def main():
    run_migrations()

    bot = init_bot()
    bot.run_polling()


if __name__ == "__main__":
    logger.info("main started")
    main()
