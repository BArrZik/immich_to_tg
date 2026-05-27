import io
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Optional, Tuple, List
from zoneinfo import ZoneInfo

import pillow_heif
from PIL import Image, ImageOps
from timezonefinder import TimezoneFinder

from immich.immich_client import immich_service
from postgres.models import MediaFile, User
from telegram import Message
from telegram.error import TelegramError

from utils.logger import logger
from bot.handlers.discussion_forward_tracker_handler import forward_tracker

pillow_heif.register_heif_opener()

_tz_finder = TimezoneFinder()


class MediaPoster:
    def __init__(self, telegram_app):
        self.app = telegram_app

    async def post_to_channel(self, user: User, media_file: MediaFile, telegram_channel_id: int) -> bool:
        """Основная функция постинга в канал"""
        try:
            media_data = await self._download_media(user, media_file)
            logger.info(f"type: {type(media_data)}")
            raw_media_data = media_data
            if not media_data:
                return False

            # Определяем формат файла
            file_ext = media_file.media_url.lower().split(".")[-1] if media_file.media_url else ""
            needs_conversion = file_ext in ["heic", "heif"]

            # Конвертируем HEIC/HEIF в JPG если нужно
            if needs_conversion:
                logger.info(f"Converting HEIC/HEIF to JPG for media {media_file.media_id}")

                # Конвертируем в памяти
                media_data = self._convert_heic_to_jpg(media_data)
                logger.info(f"type: {type(media_data)}")

            caption = await self._generate_caption(media_file)

            if media_file.media_type == "image":
                filename = media_file.media_url.split("/")[-1] if media_file.media_url else "photo.jpg"
                post = await self.app.bot.send_photo(
                    chat_id=telegram_channel_id, photo=media_data, caption=caption, parse_mode="Markdown"
                )
            elif media_file.media_type == "video":
                filename = media_file.media_url.split("/")[-1] if media_file.media_url else "video.mp4"

                post = await self._send_video_safely(
                    chat_id=telegram_channel_id,
                    video_data=media_data,
                    caption=caption,
                    filename=filename,
                    media_file=media_file,
                )
                # return post
            elif media_file.media_type == "gif":
                filename = "animation.gif"
                post = await self.app.bot.send_animation(
                    chat_id=telegram_channel_id,
                    animation=media_data,
                    filename=filename,
                    caption=caption,
                    parse_mode="Markdown",
                )
            else:
                logger.error(f"unknown media_type: {media_file.media_type}")
                return False
            logger.info(post)

            if not post:
                logger.error(f"Posting returned no message, user_id: {user.user_id}, media_uuid: {media_file.media_uuid}")
                return False

            chat_full_info = await self.app.bot.get_chat(telegram_channel_id)
            discussion_chat_id = chat_full_info.linked_chat_id

            if discussion_chat_id:
                discussion_msg_id = await forward_tracker.get(
                    channel_id=telegram_channel_id, channel_msg_id=post.message_id, timeout=10.0
                )

                if discussion_msg_id:
                    # Bot API не принимает файлы > 50 МБ. Лучше пропустить attachment, чем валить весь пост.
                    raw_size_mb = len(raw_media_data) / (1024 * 1024)
                    if raw_size_mb > 50:
                        logger.warning(
                            f"Skipping original file in discussion: too large ({raw_size_mb:.1f} MB > 50 MB), "
                            f"media_uuid: {media_file.media_uuid}"
                        )
                    else:
                        try:
                            await self.app.bot.send_document(
                                chat_id=discussion_chat_id,
                                document=raw_media_data,
                                filename=filename,
                                reply_to_message_id=discussion_msg_id,
                            )
                        except TelegramError as e:
                            # Discussion-attachment не должен заваливать основной пост
                            logger.warning(
                                f"Failed to attach original file in discussion, media_uuid: {media_file.media_uuid}. "
                                f"Error: {str(e)}"
                            )

            logger.info(
                f"Successfully posted media, user_id: {user.user_id}, telegram_id: {user.telegram_id}, media_uuid: {media_file.media_uuid}"
            )
            return True
        except TelegramError as e:
            logger.exception(
                f"Telegram error posting media, user_id: {user.user_id}, telegram_id: {user.telegram_id}, media_uuid: {media_file.media_uuid}, channel_id: {telegram_channel_id}. Error: {str(e)}"
            )
            return False
        except Exception as e:
            logger.exception(
                f"Error posting media, user_id: {user.user_id}, telegram_id: {user.telegram_id}, media_uuid: {media_file.media_uuid}. Error: {str(e)}"
            )
            return False

    def _resolve_local_time(self, dt: datetime, location: Optional[dict]) -> Tuple[datetime, str]:
        """
        Возвращает (datetime в местном времени, лейбл вида 'MSK +3').
        Приоритет: координаты → IANA-зона; иначе offset из самого datetime; иначе UTC.
        """
        # 1) Пытаемся определить IANA-зону по координатам
        tz_name: Optional[str] = None
        if location:
            lat = location.get("latitude")
            lon = location.get("longitude")
            if lat is not None and lon is not None:
                try:
                    tz_name = _tz_finder.timezone_at(lat=float(lat), lng=float(lon))
                except Exception as e:
                    logger.warning(f"timezone_at failed for ({lat},{lon}): {e}")

        if tz_name:
            try:
                tz = ZoneInfo(tz_name)
                # naive datetime трактуем как UTC, дальше переводим в локальную зону
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                local_dt = dt.astimezone(tz)
                abbr = local_dt.tzname() or tz_name.split("/")[-1]
                offset = local_dt.utcoffset()
                offset_hours = offset.total_seconds() / 3600 if offset else 0
                offset_str = f"{offset_hours:+g}"  # +3, -4.5, +0
                return local_dt, f"{abbr} {offset_str}"
            except Exception as e:
                logger.warning(f"ZoneInfo failed for {tz_name}: {e}")

        # 2) В самом datetime есть offset (например, EXIF '2024-...+03:00')
        if dt.tzinfo is not None and dt.utcoffset() is not None and dt.utcoffset().total_seconds() != 0:
            offset_hours = dt.utcoffset().total_seconds() / 3600
            return dt, f"UTC{offset_hours:+g}"

        # 3) Fallback — UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, "UTC"

    def _format_exif_info(self, info: dict) -> str:
        """Форматирование EXIF данных в текст"""
        parts = []

        if camera := info.get("camera"):
            if camera.lower() not in ["none", "null", "unknown", "undefined"]:
                parts.append(f"Снято на {camera}")

        if date_str := info.get("date"):
            try:
                dt = datetime.fromisoformat(date_str)
                local_dt, tz_label = self._resolve_local_time(dt, info.get("location"))
                formatted_date = local_dt.strftime(f"📅: %a, %d %B %Y, %H:%M {tz_label}")
                parts.append(formatted_date)
            except Exception as e:
                logger.warning(f"Error parsing date: {e}")

        photo_details = []
        if aperture := info.get("aperture"):
            photo_details.append(f"ƒ/{aperture}")
        if shutter := info.get("shutter"):
            photo_details.append(f"{shutter}")
        if focal := info.get("focal"):
            try:
                photo_details.append(f"{round(float(focal), 1):g} мм")
            except (TypeError, ValueError):
                photo_details.append(f"{focal} мм")
        if iso := info.get("iso"):
            photo_details.append(f"ISO {iso}")

        if photo_details:
            parts.append(", ".join(photo_details))

        return "\n".join(parts)

    async def _format_location(self, info: dict) -> Optional[Tuple[str, str]]:
        """Форматирование локации с определением города по координатам"""
        location = info.get("location")
        location_name = location.get("location_name", {})
        lat = location.get("latitude")
        lon = location.get("longitude")

        if not lat or not lon:
            return None

        # Пробуем определить город
        # city = await self.get_city_from_coords(float(lat), float(lon))

        # Формируем ссылку на карты
        map_url = f"https://maps.google.com/?q={lat},{lon}"

        if location["location_name"]:
            return f"[{location_name}]({map_url})", map_url
        else:
            coords_str = f"{float(lat):.5f}, {float(lon):.5f}"
            return f"[{coords_str}]({map_url})", map_url

    async def _generate_caption(self, media_file: MediaFile) -> str:
        """Генерация подписи к медиа с улучшенной обработкой локации"""
        parts = []

        if media_file.info:
            # EXIF информация
            exif_text = self._format_exif_info(media_file.info)
            if exif_text:
                parts.append(exif_text)

            # Локация
            location_info = await self._format_location(media_file.info)
            if location_info:
                location_text, _ = location_info
                parts.append(f"📍 {location_text}")

        # Генерация описания для изображений
        if media_file.media_type in ["photo", "gif"]:
            try:
                # description = await generate_image_description(media_file)
                description = ""
                parts.append(f"\n{description}")
            except Exception as e:
                print(f"Error generating description: {str(e)}")

        return "\n\n".join(parts) if parts else ""

    async def _download_media(self, user: User, media_file: MediaFile) -> Optional[bytes]:
        """Скачивание медиа с Immich"""
        try:
            logger.info("download_media")
            result = await immich_service.download_asset(user.telegram_id, media_file.media_uuid)
            return result
        except Exception as e:
            print(f"Error downloading media {media_file.media_id}: {str(e)}")
            return None

    def _convert_heic_to_jpg(self, input_data: bytes) -> bytes:
        """Конвертация HEIC/HEIF в JPG через pillow-heif (libheif в памяти)."""
        if not input_data:
            raise RuntimeError("HEIC conversion error: empty input data")

        logger.info(
            f"HEIC convert: input size={len(input_data)} bytes, "
            f"magic={input_data[:16].hex()}"
        )

        try:
            with Image.open(io.BytesIO(input_data)) as image:
                # Применяем EXIF-ориентацию и сводим к RGB (JPEG не умеет в alpha)
                image = ImageOps.exif_transpose(image)
                if image.mode != "RGB":
                    image = image.convert("RGB")

                buf = io.BytesIO()
                image.save(buf, format="JPEG", quality=90, optimize=True)
                return buf.getvalue()
        except Exception as e:
            raise RuntimeError(f"HEIC conversion error: {e}") from e

    async def _send_video_safely(
        self, chat_id: int, video_data: bytes, caption: str, media_file: MediaFile, filename: str
    ) -> Optional[Message]:
        """Безопасная отправка видео с конвертацией и сжатием. Возвращает отправленное Message или None."""
        try:
            file_size_mb = len(video_data) / (1024 * 1024)
            width = media_file.info["width"]
            height = media_file.info["height"]

            # Конвертируем если нужно
            if media_file.file_format != "mp4" or file_size_mb > 50:
                video_data, width, height = await self._convert_to_mpeg4(
                    video_data, orientation=media_file.info["orientation"]
                )

            if media_file.info["orientation"] in [5, 6, 7, 8]:
                width, height = height, width

            duration, thumbnail = self._probe_video_meta(video_data)

            try:
                logger.info(f"sending video (duration={duration}s, thumb={'yes' if thumbnail else 'no'})")
                return await self.app.bot.send_video(
                    chat_id=chat_id,
                    video=video_data,
                    caption=caption,
                    parse_mode="Markdown",
                    supports_streaming=True,
                    width=width,
                    height=height,
                    duration=duration,
                    thumbnail=thumbnail,
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=300,
                    pool_timeout=300,
                )
            except TelegramError as e:
                logger.error(f"Sending video, telegram error: {str(e)}")
                return None
        except Exception as e:
            logger.error(f"Video send failed: {str(e)}")
            # Fallback - отправка как документ
            try:
                return await self.app.bot.send_document(
                    chat_id=chat_id, document=video_data, caption=caption, parse_mode="Markdown", filename=filename
                )
            except Exception as e:
                logger.error(f"Document send also failed: {str(e)}")
                return None

    def _probe_video_meta(self, video_data: bytes) -> Tuple[int, Optional[bytes]]:
        """Возвращает (duration в секундах, jpeg-thumbnail). Без duration Telegram показывает 00:00."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_video:
                tmp_video.write(video_data)
                tmp_video.flush()

                # Длительность
                duration = 0
                probe = subprocess.run(
                    [
                        "ffprobe", "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        tmp_video.name,
                    ],
                    capture_output=True, text=True,
                )
                if probe.returncode == 0 and probe.stdout.strip():
                    try:
                        duration = int(float(probe.stdout.strip()))
                    except ValueError:
                        duration = 0

                # Кадр-превью с 1-й секунды (или 0-й если видео короткое)
                thumb_bytes: Optional[bytes] = None
                with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp_thumb:
                    seek = "00:00:01.000" if duration >= 1 else "00:00:00.000"
                    thumb = subprocess.run(
                        [
                            "ffmpeg", "-y", "-ss", seek, "-i", tmp_video.name,
                            "-frames:v", "1",
                            "-vf", "scale='min(320,iw)':-2",
                            "-q:v", "5",
                            tmp_thumb.name,
                        ],
                        capture_output=True,
                    )
                    if thumb.returncode == 0 and os.path.getsize(tmp_thumb.name) > 0:
                        with open(tmp_thumb.name, "rb") as f:
                            thumb_bytes = f.read()

                return duration, thumb_bytes
        except Exception as e:
            logger.warning(f"Video meta probe failed: {e}")
            return 0, None

    async def _convert_to_mpeg4(
        self, input_data: bytes, orientation: int = 1, max_size_mb: int = 50
    ) -> Tuple[bytes, int, int] | None:
        """Конвертирует видео с гарантированной совместимостью для Android"""
        try:
            with (
                tempfile.NamedTemporaryFile(suffix=".input") as tmp_input,
                tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_output,
            ):
                # Записываем входные данные
                tmp_input.write(input_data)
                tmp_input.flush()

                # Получаем информацию о видео
                probe = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_entries",
                        "stream=width,height,pix_fmt,color_space,color_primaries,color_transfer",
                        "-of",
                        "json",
                        tmp_input.name,
                    ],
                    capture_output=True,
                    text=True,
                )

                if probe.returncode != 0:
                    logger.error(f"FFprobe error: {probe.stderr}")
                    return None

                video_info = json.loads(probe.stdout)
                stream_info = video_info["streams"][0]
                width = int(stream_info["width"])
                height = int(stream_info["height"])
                color_transfer = stream_info.get("color_transfer", "")
                is_hdr = color_transfer in ("arib-std-b67", "smpte2084")
                logger.info(f"Source color_transfer={color_transfer or 'unknown'}, HDR={is_hdr}")

                orient_filter, need_swap = self._get_android_orientation_filter(orientation)

                # Меняем размеры если нужно
                if need_swap:
                    width, height = height, width

                # Собираем единую фильтр-цепочку
                vf_chain = []
                if orient_filter:
                    vf_chain.append(orient_filter)
                if is_hdr:
                    # HDR -> SDR через zscale (требует ffmpeg с libzimg) + tonemap
                    vf_chain.append(
                        "zscale=t=linear:npl=100,"
                        "format=gbrpf32le,"
                        "zscale=p=bt709,"
                        "tonemap=tonemap=hable:desat=0,"
                        "zscale=t=bt709:m=bt709:r=tv,"
                        "format=yuv420p"
                    )
                # Чётные размеры — требование H.264 yuv420p
                vf_chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
                vf_expr = ",".join(vf_chain)

                # Параметры для максимальной совместимости (Android Telegram native player)
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-i", tmp_input.name,
                    "-c:v", "libx264",
                    "-profile:v", "high",      # high совместим со всеми современными Android
                    "-level", "4.0",            # 1080p30, чего хватает для большинства источников
                    "-pix_fmt", "yuv420p",
                    "-vf", vf_expr,
                    # Явные теги цветового пространства — без них плееры падают на BT.601 и дают зелёный/тёмный сдвиг
                    "-colorspace", "bt709",
                    "-color_primaries", "bt709",
                    "-color_trc", "bt709",
                    "-color_range", "tv",
                    "-movflags", "+faststart",
                    "-preset", "medium",
                    "-crf", "23",
                    "-metadata:s:v:0", "rotate=0",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-ar", "44100",
                    "-ac", "2",
                    "-f", "mp4",
                    tmp_output.name,
                ]

                logger.info(f"Executing Android-compatible command: {' '.join(ffmpeg_cmd)}")
                result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)

                if result.returncode != 0:
                    logger.error(f"FFmpeg error: {result.stderr}")
                    return None

                # Проверяем результат
                if not self._verify_android_compatibility(tmp_output.name):
                    logger.error("Android compatibility verification failed")
                    return None

                # Получаем итоговые размеры
                width, height = self._get_video_dimensions(tmp_output.name, orientation)

                # Сжатие если нужно
                output_size = os.path.getsize(tmp_output.name) / (1024 * 1024)
                if output_size > max_size_mb:
                    return await self._compress_for_android(tmp_output.name, max_size_mb, width, height)

                with open(tmp_output.name, "rb") as f:
                    return f.read(), width, height

        except Exception as e:
            logger.error(f"Android conversion error: {str(e)}", exc_info=True)
            return None

    def _get_android_orientation_filter(self, orientation: int) -> Tuple[str, bool]:
        """
        Возвращает ffmpeg filter-выражение для нужной ориентации и флаг смены W/H.
        :param orientation: EXIF ориентация (1-8)
        :return: (filter-выражение или "", нужно_менять_ширину_и_высоту)
        """
        mapping = {
            1: ("", False),
            2: ("hflip", False),
            3: ("hflip,vflip", False),
            4: ("vflip", False),
            5: ("transpose=2", True),
            6: ("", True),
            7: ("transpose=0", True),
            8: ("transpose=2", True),
        }
        return mapping.get(orientation, ("", False))

    def _verify_android_compatibility(self, file_path: str) -> bool:
        """Проверяет ключевые параметры видео на совместимость с Android"""
        try:
            check_cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v",
                "-show_entries",
                "stream=codec_name,profile,pix_fmt,width,height",
                "-of",
                "json",
                file_path,
            ]
            result = subprocess.run(check_cmd, capture_output=True, text=True)
            info = json.loads(result.stdout)

            stream = info["streams"][0]
            return stream["codec_name"] == "h264" and stream["pix_fmt"] == "yuv420p"
        except Exception as e:
            logger.error(f"Android compatibility verification failed: {str(e)}")
            return False

    def _get_video_dimensions(self, file_path: str, orientation: int) -> Tuple[int, int]:
        """Возвращает правильные размеры с учетом ориентации"""
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            file_path,
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True)
        info = json.loads(result.stdout)
        w = int(info["streams"][0]["width"])
        h = int(info["streams"][0]["height"])

        return (h, w) if orientation in [5, 6, 7, 8] else (w, h)

    async def _compress_for_android(
        self, input_path: str, max_size_mb: int, width: int, height: int
    ) -> Optional[Tuple[bytes, int, int]]:
        """Специальное сжатие для Android"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".android.mp4") as tmp_out:
                # Рассчитываем битрейт
                duration = float(
                    subprocess.check_output(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_entries",
                            "format=duration",
                            "-of",
                            "default=noprint_wrappers=1:nokey=1",
                            input_path,
                        ]
                    )
                )

                target_bitrate = int((max_size_mb * 8192) / duration)  # в кбит/с

                cmd = [
                    "ffmpeg", "-y",
                    "-i", input_path,
                    "-c:v", "libx264",
                    "-profile:v", "high",
                    "-level", "4.0",
                    "-pix_fmt", "yuv420p",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-colorspace", "bt709",
                    "-color_primaries", "bt709",
                    "-color_trc", "bt709",
                    "-color_range", "tv",
                    "-b:v", f"{target_bitrate}k",
                    "-maxrate", f"{target_bitrate}k",
                    "-bufsize", f"{target_bitrate * 2}k",
                    "-preset", "medium",
                    "-movflags", "+faststart",
                    "-c:a", "aac",
                    "-b:a", "96k",
                    "-ar", "44100",
                    "-ac", "2",
                    "-f", "mp4",
                    tmp_out.name,
                ]

                logger.info("Compression started")
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

                if result.returncode != 0:
                    logger.error(f"Compression failed: {result.stderr.decode()}")
                    return None

                probe = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_entries",
                        "stream=width,height,sample_aspect_ratio,display_aspect_ratio",
                        "-of",
                        "json",
                        tmp_out.name,
                    ],
                    capture_output=True,
                    text=True,
                )

                if probe.returncode != 0:
                    logger.error(f"FFprobe error: {probe.stderr}")
                    return None

                video_info = json.loads(probe.stdout)
                width = int(video_info["streams"][0]["width"])
                height = int(video_info["streams"][0]["height"])

                with open(tmp_out.name, "rb") as f:
                    return f.read(), width, height
        except Exception as e:
            logger.error(f"Android compression failed: {str(e)}")
            return None
