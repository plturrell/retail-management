from urllib.parse import urlparse, unquote

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _make_engine_url(raw: str) -> str | URL:
    """Re-parse the DATABASE_URL so passwords with special chars (e.g. '/') are handled
    correctly regardless of whether they are percent-encoded in the env var or not."""
    try:
        parsed = urlparse(raw)
        password = unquote(parsed.password or "")
        username = unquote(parsed.username or "")
        # Extract host from query string (Cloud SQL Unix socket format)
        # e.g. ?host=/cloudsql/project:region:instance
        query = {}
        for part in (parsed.query or "").split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                query[k] = v
        host = query.pop("host", None) or parsed.hostname or "localhost"
        port = parsed.port
        database = parsed.path.lstrip("/")
        drivername = parsed.scheme  # e.g. "postgresql+asyncpg"
        return URL.create(
            drivername=drivername,
            username=username,
            password=password,
            host=host,
            port=port,
            database=database,
            query=query or None,
        )
    except Exception:
        # Fall back to the raw string if parsing fails
        return raw


engine = create_async_engine(
    _make_engine_url(settings.DATABASE_URL),
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
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
