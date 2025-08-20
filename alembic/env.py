from logging.config import fileConfig
import os, sys
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

# === добавить загрузку .env ===
from dotenv import load_dotenv

# --- гарантируем, что импортируется app.*
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # .../<repo-root>/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# загрузим переменные из .env в корне проекта
load_dotenv(PROJECT_ROOT / ".env")

# импортируем Base из приложения
from app.db import Base  # type: ignore

config = context.config

# Логирование alembic (из ini)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Метаданные для автогенерации
target_metadata = Base.metadata


def get_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set in environment")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=get_url(),
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
