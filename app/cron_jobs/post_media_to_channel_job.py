from typing import Generator, List, Dict, Any, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload
from telegram import Update
from telegram.ext import ContextTypes

from bot.check_permissions import is_user_allowed
from immich.immich_client import ImmichService, immich_service
from bot.post_to_channel import MediaPoster
from postgres.database import SessionLocal
from postgres.models import User, Album, MediaFile, ImmichHost, ApiKey
from utils.logger import logger


class MediaJobs:
    def __init__(self):
        self.immich_service = ImmichService()
        self.media_poster = None

    async def _init_poster(self, context: ContextTypes.DEFAULT_TYPE = None):
        """Инициализация MediaPoster с контекстом Telegram"""
        if context:
            self.media_poster = MediaPoster(context.application)

    def _get_active_users_batch(self, batch_size: int = 100) -> Generator[User, None, None]:
        """Генератор для пакетной загрузки активных пользователей с улучшенной обработкой"""
        logger.info(f"Starting batch processing with batch_size={batch_size}")
        offset = 0
        while True:
            db = SessionLocal()
            try:
                users = (
                    db.query(User)
                    .join(ApiKey, and_(ApiKey.user_id == User.user_id, ApiKey.deleted_at.is_(None)))
                    .join(ImmichHost, and_(ImmichHost.user_id == User.user_id, ImmichHost.deleted_at.is_(None)))
                    .options(joinedload(User.albums), joinedload(User.channels))
                    .filter(User.deleted_at.is_(None))
                    .offset(offset)
                    .limit(batch_size)
                    .all()
                )

                if not users:
                    logger.info("No more users to process")
                    break

                for user in users:
                    logger.info(f"Processing user {user.user_id} (telegram: {user.telegram_id})")
                    yield user
                    offset += 1

            except Exception as e:
                logger.error(f"Error fetching users batch (offset={offset}): {str(e)}")
                raise
            finally:
                db.close()
                logger.debug(f"Closed DB session for batch offset={offset}")

    async def _fetch_new_media(self):
        """Загрузка новых медиафайлов из Immich с улучшенной обработкой"""
        logger.info("Starting fetch_new_media")
        processed_users = 0
        processed_media = 0

        try:
            for user in self._get_active_users_batch():
                logger.info(f"fetch_new_media: get_active_users_batch - {user.telegram_id}")
                db = SessionLocal()  # Новая сессия для каждого пользователя
                try:
                    logger.info(f"Processing user {user.user_id}")
                    processed_users += 1

                    for album in user.albums:
                        if album.deleted_at:
                            logger.debug(f"Skipping deleted album {album.album_id}: {album.album_uuid}")
                            continue

                        logger.info(f"Fetching media for album {album.album_id}: {album.album_uuid}")
                        try:
                            logger.info("fetch_new_media: fetch_media_from_immich")
                            media_items = await self._fetch_media_from_immich(user.user_id, album.album_id)
                            logger.info(f"Found {len(media_items)} media items")

                            for media_data in media_items:
                                # Проверяем что файл не существует И принадлежит текущему пользователю
                                existing_media = (
                                    db.query(MediaFile)
                                    .filter(
                                        MediaFile.media_url == media_data["media_url"],
                                        # MediaFile.user_id == user.user_id,  # Добавляем проверку user_id
                                        MediaFile.deleted_at.is_(None),
                                    )
                                    .first()
                                )

                                if not existing_media:
                                    try:
                                        # Явно устанавливаем user_id для нового медиафайла
                                        media_data["user_id"] = user.user_id
                                        media_data["album_id"] = album.album_id
                                        media_file = MediaFile(**media_data)

                                        db.add(media_file)
                                        db.commit()
                                        processed_media += 1
                                        logger.info(
                                            f"Added new media {media_data['media_uuid']} for user {user.user_id}"
                                        )
                                    except Exception as e:
                                        db.rollback()
                                        logger.error(f"Error saving media {media_data['media_uuid']}: {str(e)}")
                        except Exception as e:
                            logger.error(f"Error processing album {album.album_id}: {str(e)}")
                            db.rollback()

                except Exception as e:
                    logger.error(f"Error processing user {user.user_id}: {str(e)}")
                finally:
                    db.close()
                    logger.debug(f"Closed DB session for user {user.user_id}")

        except Exception as e:
            logger.error(f"Fatal error in fetch_new_media: {str(e)}")
        finally:
            logger.info(f"Completed processing. Users: {processed_users}, Media: {processed_media}")

    async def _fetch_media_from_immich(self, user_id: int, album_id: str) -> List[Dict[str, Any]]:
        try:
            logger.info(f"Fetching media for user {user_id}, album {album_id}")

            # Получаем telegram_id пользователя
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.user_id == user_id, User.deleted_at.is_(None)).first()

                if not user:
                    logger.error(f"User {user_id} not found")
                    return []

                album = (
                    db.query(Album)
                    .filter(Album.album_id == album_id, Album.user_id == user.user_id, Album.deleted_at.is_(None))
                    .first()
                )

                if not album:
                    logger.error(f"Album {album.album_uuid} not found in database for user {user.telegram_id}")
                    return []

                logger.info(f"Using telegram_id: {user.telegram_id}, album_id: {album.album_uuid}")

            finally:
                db.close()

            # Диагностика перед вызовом
            logger.info(f"Requesting album info for {album.album_id}: {album.album_uuid}...")
            album_info = await self.immich_service.get_user_album_info(user.telegram_id, album.album_uuid)
            # logger.info(f"Received album info in {time.time() - start_time:.2f} seconds")
            logger.info("Received album info")

            if not album_info.get("assets"):
                logger.info("Album has no assets")
                return []

            return self._process_assets(album_info["assets"])

        except Exception as e:
            logger.error(f"Error in fetch_media_from_immich: {type(e).__name__}: {str(e)}")
            return []

    def _process_assets(self, assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Обработка массива ассетов из Immich"""
        processed = []
        for asset in assets:
            try:
                processed.append(
                    {
                        "media_uuid": asset["id"],
                        "media_url": asset.get("originalPath") or asset.get("originalUrl"),
                        "media_type": self._determine_media_type(asset),
                        "file_size": asset.get("exifInfo", {}).get("fileSizeInByte") or self._get_file_size(asset),
                        "file_format": self._get_file_format(asset),
                        "processed": False,
                        "error": None,
                        "info": {
                            "width": asset.get("exifInfo", {}).get("exifImageWidth"),
                            "height": asset.get("exifInfo", {}).get("exifImageHeight"),
                            "orientation": int(asset.get("exifInfo", {}).get("orientation"))
                            if asset.get("exifInfo", {}).get("orientation")
                            else 1,
                            "camera": f"{asset.get('exifInfo', {}).get('make')} {asset.get('exifInfo', {}).get('model')}",
                            "lens": asset.get("exifInfo", {}).get("lensModel"),
                            "iso": asset.get("exifInfo", {}).get("iso"),
                            "aperture": asset.get("exifInfo", {}).get("fNumber"),
                            "shutter": asset.get("exifInfo", {}).get("exposureTime"),
                            "focal": asset.get("exifInfo", {}).get("focalLength"),
                            "date": asset.get("exifInfo", {}).get("dateTimeOriginal"),
                            "location": self._get_location_info(asset.get("exifInfo", {})),
                        },
                    }
                )
            except Exception as e:
                logger.error(f"Error processing asset {asset.get('id')}: {str(e)}")

        return processed

    def _get_file_size(self, asset: dict) -> Optional[int]:
        """Получаем размер файла из разных возможных полей"""
        # Пробуем получить размер из разных возможных полей
        size_fields = ["fileSize", "size", "fileSizeInByte", "originalFileSize"]

        for field in size_fields:
            if field in asset.get("exifInfo", {}):
                return asset["exifInfo"][field]

        return None

    def _get_file_format(self, asset: dict) -> str | None:
        """Определяем формат файла"""
        # Пробуем получить из MIME-типа
        mime_type = asset.get("originalMimeType", "").lower()
        if mime_type:
            return mime_type

        media_url = asset.get("originalPath") or asset.get("originalUrl")
        if media_url:
            ext = media_url.split(".")[-1].lower()
            return ext
        return None

    def _determine_media_type(self, asset: dict) -> str:
        """Определение типа с учетом MIME-типа и расширения"""
        mime_type = asset.get("originalMimeType", "").lower()
        media_url = (asset.get("originalPath") or asset.get("originalUrl") or "").lower()

        # Проверка по MIME-типу
        if "gif" in mime_type:
            return "gif"
        if "video" in mime_type:
            return "video"
        if "image" in mime_type:
            return "image"

        # Проверка по расширению файла
        if media_url.endswith(".gif"):
            return "gif"
        if any(media_url.endswith(ext) for ext in [".mp4", ".mov", ".webm"]):
            return "video"
        if any(media_url.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".heic", ".heif"]):
            return "image"

        # Возвращаем исходный тип как fallback
        return asset["type"].lower()

    def _get_location_info(self, exif_info: Dict[str, Any]) -> Dict[str, Any]:
        """Формирование информации о местоположении"""
        location = {"location_name": None, "latitude": None, "longitude": None}
        if not exif_info:
            return location

        location_parts = []
        if exif_info.get("city"):
            location_parts.append(exif_info["city"])
        if exif_info.get("state"):
            location_parts.append(exif_info["state"])
        if exif_info.get("country"):
            location_parts.append(exif_info["country"])

        if location_parts:
            location["location_name"] = ", ".join(location_parts)

        if exif_info.get("latitude") and exif_info.get("longitude"):
            location["latitude"], location["longitude"] = exif_info["latitude"], exif_info["longitude"]
            # return f"{exif_info['latitude']}, {exif_info['longitude']}"

        return location

    # async def fetch_new_media(self):
    #     """Загрузка новых медиафайлов из Immich"""
    #     db: Session = SessionLocal()
    #     try:
    #         for user in self.get_active_users_batch():
    #             logger.debug(f"в цикле get_active_users_batch: {user.telegram_id}")
    #             try:
    #                 for album in user.albums:
    #                     if album.deleted_at:
    #                         continue
    #                     logger.debug("fetch_media_from_immich")
    #                     media_items = await self.fetch_media_from_immich(user.user_id, album.album_id)
    #                     for media_data in media_items:
    #                         if not db.query(MediaFile).filter(
    #                             MediaFile.media_url == media_data["media_url"],
    #                             MediaFile.deleted_at.is_(None)
    #                         ).first():
    #                             media_file = MediaFile(**media_data)
    #                             db.add(media_file)
    #                             db.commit()
    #             except Exception as e:
    #                 logger.error(f"Error processing user {user.user_id}: {str(e)}")
    #                 db.rollback()
    #     finally:
    #         db.close()

    async def _post_media_to_channels(self):
        """Постинг медиа в каналы пользователей"""
        if not self.media_poster:
            logger.error("MediaPoster not initialized")
            return

        db: Session = SessionLocal()
        try:
            for user in self._get_active_users_batch():
                channel = next((c for c in user.channels if not c.deleted_at), None)
                if not channel:
                    continue

                for media in (
                    db.query(MediaFile)
                    .filter(
                        MediaFile.user_id == user.user_id,
                        MediaFile.processed.is_(False),
                        MediaFile.deleted_at.is_(None),
                    )
                    .all()
                ):
                    try:
                        success = await self.media_poster.post_to_channel(user, media, channel.telegram_channel_id)
                        media.posted_to_channel = success
                        media.processed = True
                        media.error = None if success else "Posting failed"
                        db.commit()
                    except Exception as e:
                        logger.error(f"Error posting media {media.media_id}: {str(e)}")
                        db.rollback()
        finally:
            db.close()

    async def _run_media_job(self, context: ContextTypes.DEFAULT_TYPE = None):
        """Основная задача обработки медиа"""
        logger.info("init_poster")
        await self._init_poster(context)
        try:
            logger.info("fetch_new_media")
            await self._fetch_new_media()
            logger.info("post_media_to_channels")
            await self._post_media_to_channels()
        except Exception as e:
            logger.error(f"Media job error: {str(e)}")
        finally:
            await self.immich_service.close_all()

    async def manual_trigger(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔄 Запускаю обработку медиа...")
        try:
            await self._run_media_job(context)
            await update.message.reply_text("✅ Обработка медиа завершена")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            logger.error(f"Manual media job error: {str(e)}")


# Глобальный экземпляр для использования в задачах
media_jobs = MediaJobs()


async def scheduled_posting_media_to_channel_job(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая задача для планировщика"""
    await immich_service.start()
    await media_jobs._run_media_job(context)


async def manual_trigger_posting_media_to_channel_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды для ручного запуска"""
    if not is_user_allowed(update.effective_user):
        await update.message.reply_text("⛔ У вас нет прав для выполнения этой команды")
        return
    await media_jobs.manual_trigger(update, context)
