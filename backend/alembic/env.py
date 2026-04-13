import asyncio, os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import URL

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

import app.models  # noqa: F401
from app.database import Base
target_metadata = Base.metadata


def get_url():
    raw = os.environ.get("DATABASE_URL", "")
    if raw and not raw.startswith("driver://"):
        return raw
    # Build from parts (handles passwords with special chars)
    return URL.create(
        drivername="postgresql+asyncpg",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASS"],
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ["DB_NAME"],
    )


def run_migrations_offline() -> None:
    context.configure(url=get_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
