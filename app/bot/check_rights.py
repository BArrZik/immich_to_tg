from utils import config


def is_user_allowed(user) -> bool:
    """Проверка прав пользователя"""
    # Вариант 1: Проверка по telegram_id
    if user.id in config.ADMIN_IDS:
        return True

    # Вариант 2: Проверка по юзернейму (без @)
    if user.username and user.username.lower() in [u.lower() for u in config.ADMIN_USERNAMES]:
        return True

    return False