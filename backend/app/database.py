from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from app.config import settings

engine = None
async_session_factory = None

if settings.DATABASE_URL:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.ENVIRONMENT == "development",
        pool_size=20,
        max_overflow=10,
    )
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    if async_session_factory is None:
        raise RuntimeError("DATABASE_URL is not configured")
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# --- Snowflake Setup ---
snowflake_engine = None
snowflake_session_factory = None

if settings.SNOWFLAKE_ACCOUNT and settings.SNOWFLAKE_USER:
    snowflake_url = URL.create(
        "snowflake",
        username=settings.SNOWFLAKE_USER,
        password=settings.SNOWFLAKE_PASSWORD,
        host=settings.SNOWFLAKE_ACCOUNT,
        database=settings.SNOWFLAKE_DATABASE,
        query={
            "schema": settings.SNOWFLAKE_SCHEMA,
            "warehouse": settings.SNOWFLAKE_WAREHOUSE,
            "role": settings.SNOWFLAKE_ROLE,
        }
    )
    snowflake_engine = create_engine(snowflake_url, echo=settings.ENVIRONMENT == "development")
    snowflake_session_factory = sessionmaker(
        bind=snowflake_engine,
        autocommit=False,
        autoflush=False
    )

def get_snowflake_db():
    if not snowflake_session_factory:
        raise Exception("Snowflake is not configured.")
    db = snowflake_session_factory()
    try:
        yield db
    finally:
        db.close()
