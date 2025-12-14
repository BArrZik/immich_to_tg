import httpx
import asyncio
from typing import Optional, Dict, Any, Callable, Coroutine, TypeVar, Deque, List
from collections import deque
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from postgres.database import SessionLocal
from postgres.models import User, ApiKey, ImmichHost
from utils.logger import logger

T = TypeVar('T')

class ImmichClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"x-api-key": self.api_key},
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=10)
        )
        self.last_used = datetime.now()
        self.created_at = datetime.now()

    @staticmethod
    def normalize_url(url: str) -> str:
        """Нормализация URL адреса с поддержкой портов"""
        url = url.strip()

        # Удаляем возможные дублирующиеся слеши
        url = url.replace(':///', '://')

        # Обработка localhost с портом
        if url.startswith('localhost:'):
            url = f'http://{url}'
        elif url.startswith('localhost://'):
            url = url.replace('localhost://', 'http://localhost/')

        # Добавляем протокол, если отсутствует (для IP-адресов и доменных имен)
        if not url.startswith(('http://', 'https://')):
            # Если есть порт (например, 192.168.1.1:2283 или example.com:8080)
            if ':' in url.split('/')[0] and not url.startswith('['):  # Исключаем IPv6
                url = f'http://{url}'
            else:
                url = f'https://{url}'

        return url

    async def refresh(self):
        self.last_used = datetime.now()

    async def is_valid(self, ttl: timedelta) -> bool:
        return (datetime.now() - self.last_used) < ttl

    async def get_album_info(self, album_uuid: str) -> Dict[str, Any]:
        """Получение информации об альбоме с таймаутами"""
        try:
            async with asyncio.timeout(30):  # Общий таймаут операции
                response = await self.client.get(
                    f"/api/albums/{album_uuid}",
                    timeout=20.0  # Таймаут конкретного запроса
                )
                response.raise_for_status()
                return response.json()
        except asyncio.TimeoutError:
            logger.error(f"Timeout while fetching album {album_uuid}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for album {album_uuid}: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching album {album_uuid}: {str(e)}")
            raise

    async def get_albums(self) -> List[Dict[str, Any]]:
        """Get all albums from Immich"""
        await self.refresh()
        response = await self.client.get("/api/albums")
        response.raise_for_status()
        return response.json()

    async def get_album_assets(self, album_id: str) -> List[Dict[str, Any]]:
        """Get all assets from specific album"""
        await self.refresh()
        response = await self.client.get(f"/api/albums/{album_id}/assets")
        response.raise_for_status()
        return response.json()

    async def get_asset_info(self, asset_id: str) -> Dict[str, Any]:
        """Get detailed information about specific asset"""
        await self.refresh()
        response = await self.client.get(f"/api/asset/{asset_id}")
        response.raise_for_status()
        return response.json()

    async def get_asset_binary(self, asset_uuid: str) -> bytes:
        """Download asset binary data"""
        await self.refresh()
        response = await self.client.get(f"/api/assets/{asset_uuid}/original")
        response.raise_for_status()
        return response.content

    async def search_metadata(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search assets by metadata"""
        await self.refresh()
        response = await self.client.post("/api/search/metadata", json=query)
        response.raise_for_status()
        return response.json()

    async def close(self):
        try:
            await self.client.aclose()
        except Exception as e:
            logger.warning(f"Error closing client: {str(e)}")


class ImmichService:
    def __init__(
            self,
            client_ttl: timedelta = timedelta(hours=2),
            max_clients: int = 1000
    ):
        self.active_clients: Dict[int, ImmichClient] = {}
        self.client_ttl = client_ttl
        self.max_clients = max_clients
        self._lru_queue: Deque[int] = deque(maxlen=max_clients)
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self):
        """Start the cleanup task (call this when an event loop is running)"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_expired_clients())

    @staticmethod
    def client_handler(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        logger.info("running client_handler")
        @wraps(func)
        async def wrapper(self: 'ImmichService', telegram_id: int, *args, **kwargs) -> T:
            async with self._lock:
                if not await self.ensure_client(telegram_id):
                    # Попробуем создать клиента еще раз
                    db: Session = SessionLocal()
                    try:
                        user = db.query(User).filter(
                            User.telegram_id == telegram_id,
                            User.deleted_at.is_(None)
                        ).first()

                        if not user:
                            raise ValueError(f"User {telegram_id} not found")

                        # Проверяем наличие необходимых данных
                        has_host = db.query(ImmichHost).filter(
                            ImmichHost.user_id == user.user_id,
                            ImmichHost.deleted_at.is_(None)
                        ).first() is not None

                        has_key = db.query(ApiKey).filter(
                            ApiKey.user_id == user.user_id,
                            ApiKey.deleted_at.is_(None)
                        ).first() is not None

                        if not has_host or not has_key:
                            raise ValueError(
                                f"User {telegram_id} missing Immich configuration: "
                                f"host={has_host}, api_key={has_key}"
                            )
                    finally:
                        db.close()

                    # Попытка создать клиента еще раз
                    if not await self.ensure_client(telegram_id):
                        raise ValueError(f"Failed to create Immich client for user {telegram_id}")

                client = self.active_clients[telegram_id]

            try:
                return await func(self, client, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__} for user {telegram_id}: {str(e)}")
                raise

        return wrapper

    async def _get_client_for_user(self, telegram_id: int) -> Optional[ImmichClient]:
        # async with self._lock:
        # Return existing client if valid
        if telegram_id in self.active_clients:
            client = self.active_clients[telegram_id]
            if await client.is_valid(self.client_ttl):
                self._update_lru(telegram_id)
                return client
            # Client expired, close it
            await self._remove_client(telegram_id)

        # Enforce max clients limit
        if len(self.active_clients) >= self.max_clients:
            await self._remove_oldest_client()

        # Create new client
        db: Session = SessionLocal()
        try:
            user = db.query(User).filter(
                User.telegram_id == telegram_id,
                User.deleted_at.is_(None)
            ).first()

            if not user:
                logger.error(f"User with telegram_id {telegram_id} not found")
                return None

            host = db.query(ImmichHost).filter(
                ImmichHost.user_id == user.user_id,
                ImmichHost.deleted_at.is_(None)
            ).first()

            if not host:
                logger.error(f"No Immich host configured for user {telegram_id}")
                return None

            api_key = db.query(ApiKey).filter(
                ApiKey.user_id == user.user_id,
                ApiKey.deleted_at.is_(None)
            ).order_by(ApiKey.created_at.desc()).first()

            if not api_key:
                logger.error(f"No API key found for user {telegram_id}")
                return None

            try:
                # Test connection before adding client
                test_client = ImmichClient(host.host_url, api_key.api_key)
                # await test_client.get_albums()  # Test connection
                # await test_client.close()

                if not await self._test_connection(test_client):
                    logger.error(f"Connection test failed for user {telegram_id}")
                    await test_client.close()
                    return None

                client = ImmichClient(host.host_url, api_key.api_key)
                self.active_clients[telegram_id] = client
                self._lru_queue.append(telegram_id)
                logger.info(f"Created new Immich client for user {telegram_id}")
                if not await self._test_connection(client):
                    logger.error(f"Connection test failed for user {telegram_id}")
                    await client.close()
                    return None

                return client
            except Exception as e:
                logger.error(f"Failed to create Immich client for user {telegram_id}: {str(e)}")
                return None
        finally:
            db.close()

    async def _test_connection(self, client: ImmichClient) -> bool:
        """Проверка работоспособности соединения"""
        try:
            async with asyncio.timeout(5):
                response = await client.client.get("/api/users/me")
                logger.info("Connection test succeeded")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Connection test failed: {str(e)}")
            logger.error(f"Connection test failed: {e}")
            return False

    def _update_lru(self, telegram_id: int):
        """Update LRU queue for the client"""
        try:
            self._lru_queue.remove(telegram_id)
        except ValueError:
            pass
        self._lru_queue.append(telegram_id)

    async def _remove_client(self, telegram_id: int):
        """Remove and close a specific client"""
        if telegram_id in self.active_clients:
            try:
                await self.active_clients[telegram_id].close()
            finally:
                self.active_clients.pop(telegram_id, None)
                try:
                    self._lru_queue.remove(telegram_id)
                except ValueError:
                    pass

    async def _remove_oldest_client(self):
        """Remove the least recently used client"""
        if not self._lru_queue:
            return

        oldest_id = self._lru_queue[0]
        await self._remove_client(oldest_id)

    async def _cleanup_expired_clients(self):
        """Background task to clean up expired clients"""
        while True:
            await asyncio.sleep(60 * 5)  # Check every 5 minutes
            try:
                async with self._lock:
                    now = datetime.now()
                    to_remove = []

                    for uid, client in self.active_clients.items():
                        if (now - client.last_used) >= self.client_ttl:
                            to_remove.append(uid)

                    for uid in to_remove:
                        await self._remove_client(uid)

            except Exception as e:
                logger.error(f"Error in client cleanup task: {str(e)}")

    async def ensure_client(self, telegram_id: int) -> bool:
        """Ensure client exists and is valid"""
        # async with self._lock:
        if telegram_id in self.active_clients:
            client = self.active_clients[telegram_id]
            if await client.is_valid(self.client_ttl):
                return True
            await self._remove_client(telegram_id)

        client = await self._get_client_for_user(telegram_id)
        return client is not None

    @client_handler
    async def get_user_albums(self, client: ImmichClient) -> List[Dict[str, Any]]:
        """Get all albums for user"""
        return await client.get_albums()

    @client_handler
    async def get_user_album_info(self, client: ImmichClient, album_uuid: str) -> Dict[str, Any]:
        """Получение информации об альбоме с повторными попытками"""
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                return await client.get_album_info(album_uuid)
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to get album info after {max_retries} attempts")
                    raise e
                logger.warning(f"Attempt {attempt + 1} failed, retrying in {retry_delay} sec...")
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
        raise

    @client_handler
    async def get_album_assets(self, client: ImmichClient, album_id: str) -> List[Dict[str, Any]]:
        """Get all media assets from album"""
        return await client.get_album_assets(album_id)

    @client_handler
    async def get_asset_info(self, client: ImmichClient, asset_id: str) -> Dict[str, Any]:
        """Get detailed info about specific asset"""
        return await client.get_asset_info(asset_id)

    @client_handler
    async def download_asset(self, client: ImmichClient, asset_uuid: str) -> bytes:
        """Download asset binary data"""
        result = await client.get_asset_binary(asset_uuid)
        return result

    @client_handler
    async def search_assets(self, client: ImmichClient, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search assets by metadata"""
        return await client.search_metadata(query)

    async def close_all(self):
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None


# Initialize with default TTL of 2 hours and max 1000 clients
immich_service = ImmichService()