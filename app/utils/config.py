from dotenv import load_dotenv
import os

# Загружаем переменные из .env
load_dotenv()

# Получаем значения переменных
APP_ENV = os.getenv("APP_ENV")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
LOG_LEVEL = os.getenv("LOG_LEVEL")

if APP_ENV == "dev":
    BASE_URL = os.getenv("DEV_BASE_URL")
elif APP_ENV == "prod":
    BASE_URL = os.getenv("BASE_URL")
else:
    BASE_URL = None

POST_MEDIA_INTERVAL = int(os.getenv("POST_MEDIA_INTERVAL", 3600))

# Проверяем, что переменные загружены
if not all([TELEGRAM_TOKEN, BASE_URL, LOG_LEVEL]):
    raise ValueError("Не удалось загрузить переменные из .env файла")

ADMIN_IDS: list[int] = [int(i) for i in os.getenv("ADMIN_IDS", "").split(",")]
ADMIN_USERNAMES: list[str] = os.getenv("ADMIN_USERNAMES", "").split(",")
