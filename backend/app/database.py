import os
import re

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _make_engine_url(raw: str) -> URL:
    """Parse DATABASE_URL robustly, handling passwords that contain '/' or other
    special characters that break standard URL parsers.

    Supports:
      - TCP:   postgresql+asyncpg://user:pass@host:port/db
      - Unix:  postgresql+asyncpg://user:pass@/db?host=/cloudsql/...
    """
    # Allow overriding password via a separate env var (avoids URL encoding issues)
    db_password_override = os.environ.get("DATABASE_PASSWORD")

    # Use regex to extract components — avoids urlparse mishandling '/' in password
    # Pattern: scheme://user:pass@[host[:port]]/db[?query]
    m = re.match(
        r"^(?P<scheme>[^:]+)://(?P<user>[^:@]+):(?P<pass>.+)@(?P<hostpart>[^/]*)/(?P<db>[^?]*)(?:\?(?P<query>.*))?$",
        raw,
    )
    if not m:
        # Can't parse — return as-is and let SQLAlchemy try
        return raw  # type: ignore[return-value]

    scheme = m.group("scheme")
    username = m.group("user")
    password = db_password_override or m.group("pass")
    hostpart = m.group("hostpart")  # e.g. "localhost:5432" or "" (Unix socket)
    database = m.group("db")
    query_str = m.group("query") or ""

    # Parse host/port
    if hostpart and ":" in hostpart:
        host, port_str = hostpart.rsplit(":", 1)
        port: int | None = int(port_str) if port_str.isdigit() else None
    else:
        host = hostpart or None
        port = None

    # Parse query string for Unix socket host override
    query: dict[str, str] = {}
    for part in query_str.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            query[k] = v

    # Cloud SQL Unix socket path is passed via ?host=
    if not host and "host" in query:
        host = query.pop("host")

    return URL.create(
        drivername=scheme,
        username=username,
        password=password,
        host=host or None,
        port=port,
        database=database,
        query=query or None,
    )


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
