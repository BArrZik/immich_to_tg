from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    ForeignKey,
    TIMESTAMP,
    JSON,
    Text,
    BigInteger,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from postgres.database import Base


# Таблица users
class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(255), nullable=True)
    telegram_id = Column(BigInteger, nullable=False)  # Убрали unique=True
    created_at = Column(TIMESTAMP, server_default=func.now())
    deleted_at = Column(TIMESTAMP, nullable=True)  # Добавили deleted_at

    # Связи с другими таблицами
    channels = relationship("Channel", back_populates="user", cascade="all, delete")
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete")
    immich_hosts = relationship("ImmichHost", back_populates="user", cascade="all, delete")
    albums = relationship("Album", back_populates="user", cascade="all, delete")
    media_files = relationship("MediaFile", back_populates="user", cascade="all, delete")


# Таблица channels
class Channel(Base):
    __tablename__ = "channels"

    channel_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    telegram_channel_id = Column(BigInteger, nullable=False)  # Убрали unique=True
    channel_name = Column(String(255), nullable=False)
    channel_url = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    deleted_at = Column(TIMESTAMP, nullable=True)  # Добавили deleted_at

    # Связь с таблицей users
    user = relationship("User", back_populates="channels")


# Таблица api_keys
class ApiKey(Base):
    __tablename__ = "api_keys"

    key_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    api_key = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    deleted_at = Column(TIMESTAMP, nullable=True)  # Добавили deleted_at

    # Связь с таблицей users
    user = relationship("User", back_populates="api_keys")


# Таблица immich_hosts
class ImmichHost(Base):
    __tablename__ = "immich_hosts"

    host_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    host_url = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    deleted_at = Column(TIMESTAMP, nullable=True)  # Добавили deleted_at

    # Связь с таблицей users
    user = relationship("User", back_populates="immich_hosts")


# Таблица albums
class Album(Base):
    __tablename__ = "albums"

    album_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    album_uuid = Column(String(36), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    deleted_at = Column(TIMESTAMP, nullable=True)  # Добавили deleted_at

    # Связь с таблицей users
    user = relationship("User", back_populates="albums")
    # Связь с таблицей media_files
    media_files = relationship("MediaFile", back_populates="album", cascade="all, delete")


# Таблица media_files
class MediaFile(Base):
    __tablename__ = "media_files"

    media_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    media_uuid = Column(String(36), nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    album_id = Column(Integer, ForeignKey("albums.album_id", ondelete="CASCADE"), nullable=False)
    media_url = Column(String(255), nullable=False)
    media_type = Column(String(50), nullable=False)  # Тип медиа: photo, video и т.д.
    processed = Column(Boolean, default=False)
    error = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    deleted_at = Column(TIMESTAMP, nullable=True)  # Добавили deleted_at
    file_size = Column(Integer, nullable=True)
    file_format = Column(String(30), nullable=True)

    # Метаданные медиа в формате JSON
    info = Column(JSON, nullable=True)  # Пример: {"location": "New York", "iso": "100", "aperture": "f/2.8", ...}

    # Связь с таблицей albums
    album = relationship("Album", back_populates="media_files")
    # Связь с таблицей users
    user = relationship("User", back_populates="media_files")
