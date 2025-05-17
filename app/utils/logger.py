import logging
import os

from pythonjsonlogger import json

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

class SingletonLogger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._configure_logger()
        return cls._instance

    def _configure_logger(self):
        # Настройка формата JSON
        log_handler = logging.StreamHandler()
        formatter = json.JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
            datefmt="%Y-%m-%dT%H:%M:%SZ"
        )
        log_handler.setFormatter(formatter)

        # Настройка базового логгера
        logging.basicConfig(
            level=LOG_LEVEL.upper(),
            handlers=[log_handler]
        )

        self.logger = logging.getLogger(__name__)

    def get_logger(self):
        return self.logger

# Создаем экземпляр логгера
logger = SingletonLogger().get_logger()