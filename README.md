# Immich to Telegram Bot

Telegram бот для автоматической публикации медиа из альбомов Immich в Telegram каналы.

## Возможности

- Автоматическая синхронизация медиа из Immich альбомов
- Конвертация HEIC/HEIF в JPG
- Конвертация видео в H.264 (совместимость с Android)
- Автоматическое сжатие файлов > 50MB
- Извлечение EXIF метаданных для подписей
- Поддержка обсуждений каналов

## Быстрый старт

```bash
# Development
docker-compose -f docker-compose.dev.yml up --build

# Production
docker-compose up --build
```

## Переменные окружения

```env
TELEGRAM_TOKEN=your_bot_token
ADMIN_IDS=123456789,987654321
POSTGRES_USER=user
POSTGRES_PASSWORD=password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=immich_tg
APP_ENV=dev
POST_MEDIA_INTERVAL=3600
```

---

## Архитектура

### Общая схема системы

```mermaid
flowchart TB
    subgraph External["Внешние сервисы"]
        TG["Telegram API"]
        IMMICH["Immich Server"]
    end

    subgraph App["Application"]
        BOT["Telegram Bot<br/>(python-telegram-bot)"]

        subgraph Handlers["Handlers"]
            SETUP["Setup Handlers<br/>(ConversationHandler)"]
            DELETE["Delete Handler"]
            FORWARD["Forward Tracker"]
            ERROR["Error Handler"]
        end

        subgraph Services["Services"]
            POSTER["MediaPoster"]
            IMMICH_SVC["ImmichService<br/>(Connection Pool)"]
        end

        subgraph Jobs["Cron Jobs"]
            MEDIA_JOB["MediaJob<br/>(POST_MEDIA_INTERVAL)"]
            CLEANUP_JOB["Cleanup Job<br/>(60s)"]
        end
    end

    subgraph Storage["Storage"]
        PG[("PostgreSQL")]
        TMP["Temp Files<br/>/tmp/*.mp4, *.jpg"]
    end

    subgraph Tools["Media Tools"]
        FFMPEG["FFmpeg"]
        IMAGEMAGICK["ImageMagick"]
    end

    TG <--> BOT
    BOT --> Handlers
    BOT --> Jobs

    SETUP --> PG
    DELETE --> PG
    MEDIA_JOB --> IMMICH_SVC
    MEDIA_JOB --> POSTER
    MEDIA_JOB --> PG

    IMMICH_SVC <--> IMMICH
    POSTER --> TG
    POSTER --> TMP
    POSTER --> FFMPEG
    POSTER --> IMAGEMAGICK

    CLEANUP_JOB --> FORWARD
```

### ER-диаграмма базы данных

```mermaid
erDiagram
    User ||--o| Channel : has
    User ||--o| ApiKey : has
    User ||--o| ImmichHost : has
    User ||--o{ Album : has
    User ||--o{ MediaFile : owns
    Album ||--o{ MediaFile : contains

    User {
        int user_id PK
        bigint telegram_id UK
        string username
        datetime created_at
        datetime deleted_at
    }

    Channel {
        int channel_id PK
        int user_id FK
        bigint telegram_channel_id
        string channel_name
        string channel_url
        datetime deleted_at
    }

    ApiKey {
        int key_id PK
        int user_id FK
        string api_key
        datetime deleted_at
    }

    ImmichHost {
        int host_id PK
        int user_id FK
        string host_url
        datetime deleted_at
    }

    Album {
        int album_id PK
        int user_id FK
        string album_uuid
        datetime deleted_at
    }

    MediaFile {
        int media_id PK
        string media_uuid UK
        int user_id FK
        int album_id FK
        string media_url
        string media_type
        boolean processed
        string error
        bigint file_size
        string file_format
        json info
        datetime deleted_at
    }
```

### Поток настройки бота (ConversationHandler)

```mermaid
stateDiagram-v2
    [*] --> Start: /start

    Start --> CheckData: Проверка БД

    CheckData --> ChannelName: Нет канала
    CheckData --> ImmichHost: Есть канал,<br/>нет хоста
    CheckData --> ApiKey: Есть хост,<br/>нет ключа
    CheckData --> AlbumUUID: Есть ключ,<br/>нет альбома
    CheckData --> Complete: Все данные есть

    ChannelName --> ValidateChannel: Ввод канала
    ValidateChannel --> ImmichHost: Валидный
    ValidateChannel --> ChannelName: Ошибка

    ImmichHost --> ValidateHost: Ввод URL
    ValidateHost --> ApiKey: Валидный
    ValidateHost --> ImmichHost: Ошибка

    ApiKey --> ValidateKey: Ввод ключа
    ValidateKey --> AlbumUUID: Валидный
    ValidateKey --> ApiKey: Ошибка

    AlbumUUID --> ValidateAlbum: Ввод UUID
    ValidateAlbum --> Complete: Валидный
    ValidateAlbum --> AlbumUUID: Ошибка

    Complete --> [*]: ConversationHandler.END

    ChannelName --> Cancelled: /cancel
    ImmichHost --> Cancelled: /cancel
    ApiKey --> Cancelled: /cancel
    AlbumUUID --> Cancelled: /cancel
    Cancelled --> [*]
```

### Поток обработки медиа (Cron Job)

```mermaid
flowchart TD
    subgraph Trigger["Триггер"]
        CRON["Каждые POST_MEDIA_INTERVAL сек"]
        MANUAL["/process_media (admin)"]
    end

    subgraph FetchPhase["1. Fetch New Media"]
        F1["Загрузить активных<br/>пользователей (batch=100)"]
        F2["Для каждого user:<br/>получить альбомы"]
        F3["Запросить медиа<br/>из Immich API"]
        F4["Сохранить новые<br/>MediaFile в БД<br/>(processed=False)"]
    end

    subgraph PostPhase["2. Post Media"]
        P1["Найти необработанные<br/>MediaFile"]
        P2["Скачать файл<br/>из Immich"]
        P3{"Тип файла?"}
        P4["HEIC - JPG<br/>(ImageMagick)"]
        P5["Video - H.264<br/>(FFmpeg)"]
        P6{"Размер > 50MB?"}
        P7["Сжать видео"]
        P8["Отправить в канал"]
        P9["Обновить<br/>processed=True"]
        P10["Отправить в обсуждение<br/>(если есть)"]
    end

    CRON --> F1
    MANUAL --> F1
    F1 --> F2 --> F3 --> F4
    F4 --> P1
    P1 --> P2 --> P3
    P3 -->|HEIC/HEIF| P4 --> P8
    P3 -->|Video| P5 --> P6
    P3 -->|JPG/PNG| P8
    P6 -->|Да| P7 --> P8
    P6 -->|Нет| P8
    P8 --> P9 --> P10
```

### ImmichService - управление пулом клиентов

```mermaid
flowchart LR
    subgraph Request["Запрос"]
        FUNC["@client_handler<br/>decorated function"]
    end

    subgraph ImmichService["ImmichService"]
        CHECK{"Клиент<br/>существует?"}
        TTL{"TTL<br/>истёк?"}
        LRU{"Клиентов<br/>> 1000?"}

        CREATE["Создать<br/>ImmichClient"]
        EVICT["Удалить<br/>старейший"]
        UPDATE["Обновить<br/>last_used"]

        POOL[("active_clients<br/>Dict")]
    end

    subgraph Background["Фоновые задачи"]
        CLEANUP["cleanup_task<br/>(каждые 5 мин)"]
    end

    FUNC --> CHECK
    CHECK -->|Нет| LRU
    CHECK -->|Да| TTL
    TTL -->|Да| CREATE
    TTL -->|Нет| UPDATE
    LRU -->|Да| EVICT --> CREATE
    LRU -->|Нет| CREATE
    CREATE --> POOL
    UPDATE --> POOL

    CLEANUP -->|Удалить expired| POOL
```

### Структура компонентов

```mermaid
flowchart TB
    subgraph app["app/"]
        MAIN["main.py"]

        subgraph bot["bot/"]
            BOT_CLIENT["bot_client.py"]
            POST["post_to_channel.py"]
            PERMS["check_permissions.py"]

            subgraph handlers["handlers/"]
                ERR["error_handler.py"]
                DEL["delete_all_handler.py"]
                FWD["discussion_forward_tracker_handler.py"]

                subgraph setup["setup_handlers/"]
                    SETUP_H["setup_handlers.py"]
                    CONSTS["setup_handler_consts.py"]
                    START["start_handler.py"]
                    CHANNEL["channel_name_handler.py"]
                    HOST["immich_host_handler.py"]
                    KEY["api_key_handler.py"]
                    ALBUM["album_uuid_handler.py"]
                    CANCEL["cancel_handler.py"]
                end
            end
        end

        subgraph cron["cron_jobs/"]
            MEDIA_JOB["post_media_to_channel_job.py"]
        end

        subgraph immich["immich/"]
            IMMICH_CLIENT["immich_client.py"]
        end

        subgraph postgres["postgres/"]
            DB["database.py"]
            MODELS["models.py"]
        end

        subgraph utils["utils/"]
            CONFIG["config.py"]
            LOGGER["logger.py"]
        end
    end

    MAIN --> BOT_CLIENT
    BOT_CLIENT --> handlers
    BOT_CLIENT --> MEDIA_JOB
    MEDIA_JOB --> IMMICH_CLIENT
    MEDIA_JOB --> POST
    POST --> IMMICH_CLIENT
    handlers --> MODELS
    MEDIA_JOB --> MODELS
    MODELS --> DB
```

### Sequence диаграмма постинга медиа

```mermaid
sequenceDiagram
    participant JQ as JobQueue
    participant MJ as MediaJob
    participant IS as ImmichService
    participant IM as Immich Server
    participant DB as PostgreSQL
    participant MP as MediaPoster
    participant FF as FFmpeg
    participant TG as Telegram

    JQ->>MJ: run_media_job()

    rect rgb(200, 220, 255)
        Note over MJ,DB: Phase 1: Fetch New Media
        MJ->>DB: get active users (batch=100)
        loop Для каждого user
            MJ->>DB: get albums
            MJ->>IS: get_album_assets()
            IS->>IM: GET /albums/{id}
            IM-->>IS: assets[]
            IS-->>MJ: assets[]
            MJ->>DB: insert new MediaFile(processed=False)
        end
    end

    rect rgb(220, 255, 220)
        Note over MJ,TG: Phase 2: Post Media
        MJ->>DB: get unprocessed MediaFile
        loop Для каждого media
            MJ->>MP: post_to_channel()
            MP->>IS: get_asset_binary()
            IS->>IM: GET /assets/{id}/original
            IM-->>IS: binary data
            IS-->>MP: binary data

            alt Video файл
                MP->>FF: convert to H.264
                FF-->>MP: converted.mp4
            end

            MP->>TG: send_video/photo()
            TG-->>MP: message_id
            MP->>DB: update processed=True
        end
    end
```

---

## Команды бота

| Команда | Описание | Доступ |
|---------|----------|--------|
| `/start` | Запуск настройки бота | Все |
| `/delete_my_data` | Удаление всех данных пользователя | Все |
| `/process_media` | Ручной запуск обработки медиа | Админы |


## Разработка

```bash
# Линтинг
ruff check app/
ruff format app/

# Миграции БД
cd app && alembic upgrade head
cd app && alembic revision --autogenerate -m "description"
```

## Лицензия

MIT
