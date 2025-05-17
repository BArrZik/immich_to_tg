from sqlalchemy.orm import Session
from sqlalchemy import update
import datetime


from postgres.database import SessionLocal
from postgres.models import User, Channel, ApiKey, ImmichHost, Album, MediaFile

async def delete_all_handler(bot_update, context):
    db: Session = SessionLocal()
    telegram_id = bot_update.message.from_user.id

    # Находим пользователя
    user = db.query(User).filter(User.telegram_id == telegram_id, User.deleted_at.is_(None)).first()

    if not user:
        bot_update.message.reply_text("Пользователь не найден.")
        return

    # Устанавливаем deleted_at для пользователя и всех связанных данных
    now = datetime.datetime.now(datetime.UTC)
    user.deleted_at = now

    db.execute(
        update(Channel).where(Channel.user_id == user.user_id).values(deleted_at=now))
    db.execute(
        update(ApiKey).where(ApiKey.user_id == user.user_id).values(deleted_at=now))
    db.execute(
        update(ImmichHost).where(ImmichHost.user_id == user.user_id).values(deleted_at=now))
    db.execute(
        update(Album).where(Album.user_id == user.user_id).values(deleted_at=now))
    db.execute(
        update(MediaFile).where(MediaFile.user_id == user.user_id).values(deleted_at=now))

    db.commit()
    bot_update.message.reply_text("Все ваши данные были удалены.")