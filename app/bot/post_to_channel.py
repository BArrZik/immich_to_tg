# services/post_to_channel.py
# import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import Optional, Tuple, List
# import httpx
# from geopy.geocoders import Nominatim
# from telegram import InputMediaPhoto, InputMediaVideo, Update
# from utils.image_analyzer import generate_image_description
from immich.immich_client import immich_service
from postgres.models import MediaFile, User
# from utils import config
from telegram.error import TelegramError

from utils.logger import logger

# from PIL import Image
# import io
# import pyheif
# import piexif
from bot.handlers.discussion_forward_tracker_handler import forward_tracker


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
            file_ext = media_file.media_url.lower().split('.')[-1] if media_file.media_url else ''
            needs_conversion = file_ext in ['heic', 'heif']
            # converted_file = None

            # try:
            # Конвертируем HEIC/HEIF в JPG если нужно
            if needs_conversion:

                logger.info(f"Converting HEIC/HEIF to JPG for media {media_file.media_id}")

                # Конвертируем в памяти
                media_data = self._convert_heic_to_jpg(media_data)
                logger.info(f"type: {type(media_data)}")

            caption = await self._generate_caption(media_file)
            # caption = ""

            filename = f"base_filename.{file_ext}"

            if media_file.media_type == 'image':
                filename = media_file.media_url.split('/')[-1] if media_file.media_url else 'photo.jpg'
                post = await self.app.bot.send_photo(
                    chat_id=telegram_channel_id,
                    photo=media_data,
                    caption=caption,
                    parse_mode='Markdown'
                )
            elif media_file.media_type == 'video':
                filename = media_file.media_url.split('/')[-1] if media_file.media_url else 'video.mp4'

                post = await self._send_video_safely(
                    chat_id=telegram_channel_id,
                    video_data=media_data,
                    caption=caption,
                    filename=filename,
                    media_file=media_file
                )
                # return post
            elif media_file.media_type == 'gif':
                filename = "animation.gif"
                post = await self.app.bot.send_animation(
                    chat_id=telegram_channel_id,
                    animation=media_data,
                    filename=filename,
                    caption=caption,
                    parse_mode='Markdown'
                )
            else:
                logger.error(f"unknown media_type: {media_file.media_type}")
                return False
            logger.info(post)

            chat_full_info = await self.app.bot.get_chat(telegram_channel_id)
            discussion_chat_id = chat_full_info.linked_chat_id
            main_post_message_id = post.message_id

            if discussion_chat_id:
                discussion_msg_id = await forward_tracker.get(
                    channel_id=telegram_channel_id,
                    channel_msg_id=post.message_id,
                    timeout=5.0
                )

                if discussion_msg_id:
                    await self.app.bot.send_document(
                        chat_id=discussion_chat_id,
                        document=raw_media_data,
                        filename=filename,
                        reply_to_message_id=discussion_msg_id
                    )

            # if discussion_chat_id:
            #     # 2. Use the helper function to get the correct discussion ID (D)
            #     discussion_reply_id = await self.get_discussion_channel_message_id(
            #         main_message_id=main_post_message_id,
            #         discussion_chat_id=discussion_chat_id
            #     )
            #
            #     if discussion_reply_id:
            #         # 3. Use the discussion ID (D) as reply_to_message_id
            #         #    when sending the document to the discussion group.
            #         try:
            #             post_doc = await self.app.bot.send_document(
            #                 chat_id=discussion_chat_id,
            #                 document=raw_media_data,
            #                 filename=filename,
            #                 # Use the found discussion ID (D) here
            #                 reply_to_message_id=discussion_reply_id
            #             )
            #             logger.info(f"Document successfully sent to comments using D: {post_doc}")
            #             logger.info(
            #                 f"Successfully posted media, user_id: {user.user_id}, telegram_id: {user.telegram_id}, media_uuid: {media_file.media_uuid}")
            #             return True
            #
            #         except Exception as e:
            #             logger.error(f"Failed to send document to comments using D: {e}")
            #             # If this still fails, there might be a separate permission or file size issue
            #             return False
            #     else:
            #         logger.error("Could not find discussion message ID, skipping document post to comments.")
            #         return False  # Or True, depending on whether the document post is critical
            # else:
            #     logger.warning("No linked discussion chat found, skipping document post to comments.")
            #     return True  # Post to main channel succeeded, but comments skipped

            logger.info(f"Successfully posted media, user_id: {user.user_id}, telegram_id: {user.telegram_id}, media_uuid: {media_file.media_uuid}")
            return True
            # finally:
            #     # Закрываем временные файлы если они были
            #     if converted_file:
            #         converted_file.close()
        except TelegramError as e:
            print(f"Telegram error posting media, user_id: {user.user_id}, telegram_id: {user.telegram_id}, media_uuid: {media_file.media_uuid}, channel_id: {telegram_channel_id}. Error: {str(e)}")
            return False
        except Exception as e:
            print(f"Error posting media, user_id: {user.user_id}, telegram_id: {user.telegram_id}, media_uuid: {media_file.media_uuid}. Error: {str(e)}")
            return False
    #
    # async def get_discussion_channel_message_id(self, main_message_id: int, discussion_chat_id: int) -> Optional[int]:
    #     """
    #     Finds the message ID (D) in the discussion chat that corresponds
    #     to the original message ID (M) in the main channel.
    #     """
    #     logger.info(f"Attempting to find discussion message ID for main ID: {main_message_id}")
    #
    #     # We must limit the updates, as fetching all can be slow.
    #     # The new post is usually one of the most recent.
    #     # The timeout keeps the connection open briefly, waiting for the update.
    #     # You might need to adjust limit and timeout based on your bot's traffic.
    #     await asyncio.sleep(5)
    #
    #     logger.info(await self.app.bot.get_updates(
    #         timeout=5,  # Wait up to 5 seconds for new updates
    #         limit=20  # Check the last 20 updates
    #     ))
    #     logger.info(f"Got updates for message ID for main ID: {main_message_id}")
    #

        # Check updates in reverse order (most recent first) for efficiency
        # for update in reversed(updates):
        #     message = update.effective_message
        #     if message and message.chat_id == discussion_chat_id:
        #         logger.info(f"Found discussion message ID for main ID: {message.message_id} - {message}")
        #         # Check if this message was forwarded from the main message (M)
        #         # The API returns the *original* channel message ID (M)
        #         # in forward_from_message_id when seen in the discussion group updates.
        #         if message.forward_origin.message_id == main_message_id:
        #             logger.info(f"Found discussion message ID: {message.message_id}")
        #             return message.message_id  # This is the ID D
        #
        # logger.warning(f"Could not find discussion message ID for main ID: {main_message_id}")
        # return None

    def _format_exif_info(self, info: dict) -> str:
        """Форматирование EXIF данных в текст"""
        # exif = info.get('exifInfo', {})
        parts = []

        if camera := info.get('camera'):
            parts.append(f"Снято на {camera}")

        if date_str := info.get('date'):
            try:
                dt = datetime.fromisoformat(date_str)
                formatted_date = dt.strftime("📅: %a, %d %B %Y, %H:%M %Z")
                parts.append(formatted_date)
            except:
                pass

        photo_details = []
        if aperture := info.get('aperture'):
            photo_details.append(f"ƒ/{aperture}")
        if shutter := info.get('shutter'):
            photo_details.append(f"{shutter}")
        if focal := info.get('focal'):
            photo_details.append(f"{focal} мм")
        if iso := info.get('iso'):
            photo_details.append(f"ISO {iso}")

        if photo_details:
            parts.append(", ".join(photo_details))

        return "\n".join(parts)

    async def _format_location(self, info: dict) -> Optional[Tuple[str, str]]:
        """Форматирование локации с определением города по координатам"""
        location = info.get("location")
        location_name = location.get('location_name', {})
        lat = location.get('latitude')
        lon = location.get('longitude')

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
        if media_file.media_type in ['photo', 'gif']:
            try:
                # description = await generate_image_description(media_file)
                description = "test description"
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
        """Улучшенная конвертация HEIC в JPG с проверкой ImageMagick"""
        try:
            # Проверяем доступность convert
            if not shutil.which('convert'):
                raise RuntimeError("ImageMagick (convert) not found in PATH")

            with tempfile.NamedTemporaryFile(suffix='.heic') as tmp_input:
                tmp_input.write(input_data)
                tmp_input.flush()

                with tempfile.NamedTemporaryFile(suffix='.jpg') as tmp_output:
                    # Добавляем параметры для лучшего качества
                    subprocess.run([
                        'convert',
                        tmp_input.name,
                        '-quality', '90%',  # Оптимальное качество
                        '-auto-orient',  # Автоповорот
                        tmp_output.name
                    ], check=True, capture_output=True)

                    return tmp_output.read()

        except subprocess.CalledProcessError as e:
            error_msg = f"Conversion failed: {e.stderr.decode().strip()}"
            raise RuntimeError(error_msg)
        except Exception as e:
            raise RuntimeError(f"HEIC conversion error: {str(e)}")

    async def _send_video_safely(self, chat_id: int, video_data: bytes, caption: str, media_file: MediaFile, filename: str) -> bool:
        """Безопасная отправка видео с конвертацией и сжатием"""
        try:
            # Проверяем формат и размер
            # file_format = media_file.file_format
            file_size_mb = len(video_data) / (1024 * 1024)
            width = media_file.info["width"]
            height = media_file.info["height"]

            # Конвертируем если нужно
            if media_file.file_format != 'mp4' or file_size_mb > 50:
                video_data, width, height = await self._convert_to_mpeg4(video_data, orientation=media_file.info["orientation"])
                # filename = 'video.mp4'

            if media_file.info["orientation"] in [5, 6, 7, 8]:
                width, height = height, width

            # Отправляем видео
            try:
                logger.info("sending video")
                await self.app.bot.send_video(
                    chat_id=chat_id,
                    video=video_data,
                    caption=caption,
                    parse_mode='Markdown',
                    supports_streaming=True,
                    width=width,
                    height=height,
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=300,
                    pool_timeout=300
                )
                return True
            except TelegramError as e:
                logger.error(f"Sending video, telegram error: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Video send failed: {str(e)}")
            # Fallback - отправка как документ
            try:
                await self.app.bot.send_document(
                    chat_id=chat_id,
                    document=video_data,
                    caption=caption,
                    parse_mode='Markdown',
                    filename=filename
                )
                return True
            except Exception as e:
                logger.error(f"Document send also failed: {str(e)}")
                return False

    async def _convert_to_mpeg4(self, input_data: bytes, orientation: int = 1, max_size_mb: int = 50) -> Tuple[
                                                                                                            bytes, int, int] | None:
        """Конвертирует видео с гарантированной совместимостью для Android"""
        try:
            with tempfile.NamedTemporaryFile(suffix='.input') as tmp_input, \
                    tempfile.NamedTemporaryFile(suffix='.mp4') as tmp_output:

                # Записываем входные данные
                tmp_input.write(input_data)
                tmp_input.flush()

                # Получаем информацию о видео
                probe = subprocess.run([
                    'ffprobe',
                    '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=width,height,pix_fmt,color_space,color_primaries,color_transfer',
                    '-of', 'json',
                    tmp_input.name
                ], capture_output=True, text=True)

                if probe.returncode != 0:
                    logger.error(f"FFprobe error: {probe.stderr}")
                    return None

                video_info = json.loads(probe.stdout)
                stream_info = video_info['streams'][0]
                width = int(stream_info['width'])
                height = int(stream_info['height'])
                orient_params, need_swap = self._get_android_orientation_params(orientation)

                # Меняем размеры если нужно
                if need_swap:
                    width, height = height, width

                # Базовые параметры для максимальной совместимости
                ffmpeg_cmd = [
                    'ffmpeg', '-y',
                    '-i', tmp_input.name,
                    # Видео параметры (критически важные для Android)
                    '-c:v', 'libx264',
                    '-profile:v', 'baseline',  # Самый совместимый профиль
                    '-level', '3.0',  # Поддержка старых устройств
                    '-pix_fmt', 'yuv420p',  # Единственный надежный формат
                    '-movflags', '+faststart',  # Для потокового воспроизведения
                    '-preset', 'fast',  # Оптимальное соотношение скорость/качество
                    '-crf', '23',  # Качество (23 - хороший баланс)

                    # Гарантируем ключевые кадры
                    '-force_key_frames', 'expr:gte(n,0+n_forced*3)',
                    '-x264-params', 'scenecut=0:keyint=30:min-keyint=30:no-scenecut=1',

                    *orient_params,  # Добавляем параметры ориентации
                    '-metadata:s:v:0', 'rotate=0',  # Сбрасываем метаданные поворота

                    # Аудио параметры
                    '-c:a', 'aac',
                    '-b:a', '128k',
                    '-ar', '44100',
                    '-ac', '2',

                    # Важные флаги
                    '-strict', 'experimental',  # Для полной совместимости
                    '-f', 'mp4',  # Явное указание формата

                    tmp_output.name
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

                with open(tmp_output.name, 'rb') as f:
                    return f.read(), width, height

        except Exception as e:
            logger.error(f"Android conversion error: {str(e)}", exc_info=True)
            return None

    def _get_android_orientation_params(self, orientation: int) -> Tuple[List[str], bool]:
        """
        Возвращает параметры трансформации видео и флаг необходимости смены размеров
        :param orientation: EXIF ориентация (1-8)
        :return: (ffmpeg параметры, нужно_менять_ширину_и_высоту)
        """
        # 1 = Нормальная ориентация
        if orientation == 1:
            return [], False

        # 2 = Зеркальное отражение по вертикали
        elif orientation == 2:
            return ['-vf', 'hflip'], False

        # 3 = Поворот на 180°
        elif orientation == 3:
            return ['-vf', 'hflip,vflip'], False

        # 4 = Зеркальное отражение по горизонтали
        elif orientation == 4:
            return ['-vf', 'vflip'], False

        # 5 = Зеркальное отражение по вертикали + поворот 90° против часовой
        elif orientation == 5:
            return ['-vf', 'transpose=2'], True

        # 6 test
        elif orientation == 6:
            return [], True

        # 7 = Зеркальное отражение по вертикали + поворот 90° по часовой
        elif orientation == 7:
            return ['-vf', 'transpose=0'], True

        # 8 = Поворот на 90° против часовой
        elif orientation == 8:
            return ['-vf', 'transpose=2'], True

        return [], False

    def _verify_android_compatibility(self, file_path: str) -> bool:
        """Проверяет ключевые параметры видео на совместимость с Android"""
        try:
            check_cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'v',
                '-show_entries', 'stream=codec_name,profile,pix_fmt,width,height',
                '-of', 'json',
                file_path
            ]
            result = subprocess.run(check_cmd, capture_output=True, text=True)
            info = json.loads(result.stdout)

            stream = info['streams'][0]
            return (stream['codec_name'] == 'h264' and
                    'Baseline' in stream['profile'] and
                    stream['pix_fmt'] == 'yuv420p')
        except Exception as e:
            logger.error(f"Android compatibility verification failed: {str(e)}")
            return False


    def _get_video_dimensions(self, file_path: str, orientation: int) -> Tuple[int, int]:
        """Возвращает правильные размеры с учетом ориентации"""
        probe_cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'json',
            file_path
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True)
        info = json.loads(result.stdout)
        w = int(info['streams'][0]['width'])
        h = int(info['streams'][0]['height'])

        return (h, w) if orientation in [5, 6, 7, 8] else (w, h)


    async def _compress_for_android(self, input_path: str, max_size_mb: int, width: int, height: int) -> Optional[
        Tuple[bytes, int, int]]:
        """Специальное сжатие для Android"""
        try:
            with tempfile.NamedTemporaryFile(suffix='.android.mp4') as tmp_out:
                # Рассчитываем битрейт
                duration = float(subprocess.check_output([
                    'ffprobe', '-v', 'error',
                    '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    input_path
                ]))

                target_bitrate = int((max_size_mb * 8192) / duration)  # в кбит/с

                cmd = [
                    'ffmpeg', '-y',
                    '-i', input_path,
                    '-c:v', 'libx264',
                    '-profile:v', 'baseline',
                    '-level', '3.0',
                    '-pix_fmt', 'yuv420p',
                    '-b:v', f'{target_bitrate}k',
                    '-maxrate', f'{target_bitrate}k',
                    '-bufsize', f'{target_bitrate * 2}k',
                    '-preset', 'fast',
                    '-movflags', '+faststart',
                    '-c:a', 'aac',
                    '-b:a', '96k',  # Чуть меньше аудио для видео
                    '-ar', '44100',
                    '-f', 'mp4',
                    tmp_out.name
                ]

                logger.info("Compression started")
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True
                )

                if result.returncode != 0:
                    logger.error(f"Compression failed: {result.stderr.decode()}")
                    return None

                probe = subprocess.run([
                    'ffprobe',
                    '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=width,height,sample_aspect_ratio,display_aspect_ratio',
                    '-of', 'json',
                    tmp_out.name
                ], capture_output=True, text=True)

                if probe.returncode != 0:
                    logger.error(f"FFprobe error: {probe.stderr}")
                    return None

                video_info = json.loads(probe.stdout)
                width = int(video_info['streams'][0]['width'])
                height = int(video_info['streams'][0]['height'])

                with open(tmp_out.name, 'rb') as f:
                    return f.read(), width, height
        except Exception as e:
            logger.error(f"Android compression failed: {str(e)}")
            return None
