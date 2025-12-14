import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy import pool

# Импортируем после добавления пути
from postgres.models import Base
from postgres.database import DATABASE_URL

config = context.config
fileConfig(config.config_file_name)  # type: ignore

target_metadata = Base.metadata

def run_migrations_offline():
    url = DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable_config = {
        "sqlalchemy.url": DATABASE_URL
    }

    connectable = engine_from_config(
        connectable_config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()