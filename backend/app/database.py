import os
import re

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _parse_engine_config(raw: str) -> tuple[URL, dict]:
    """Parse DATABASE_URL into a SQLAlchemy URL + connect_args dict.

    Handles passwords with '/' and Cloud SQL Unix socket URLs of the form:
      postgresql+asyncpg://user:pass@/db?host=/cloudsql/project:region:instance

    Returns (url, connect_args) where the Unix socket path is moved to
    connect_args['host'] so asyncpg receives it correctly.
    """
    # Greedy regex — the password may contain '/'
    m = re.match(
        r"^(?P<scheme>[^:]+)://(?P<user>[^:@]+):(?P<pass>.+)@(?P<hostpart>[^/]*)/(?P<db>[^?]*)(?:\?(?P<query>.*))?$",
        raw,
    )
    if not m:
        return raw, {}  # type: ignore[return-value]

    scheme   = m.group("scheme")
    username = m.group("user")
    password = os.environ.get("DATABASE_PASSWORD") or m.group("pass")
    hostpart = m.group("hostpart")   # empty string for Unix socket URLs
    database = m.group("db")
    query_str = m.group("query") or ""

    # Parse ?key=value pairs
    query: dict[str, str] = {}
    for part in query_str.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            query[k] = v

    connect_args: dict = {}

    # Cloud SQL Unix socket: ?host=/cloudsql/...
    # Move the socket path out of the query string into connect_args so
    # asyncpg receives it as a keyword argument rather than a URL component.
    unix_socket_host = query.pop("host", None)
    if unix_socket_host and unix_socket_host.startswith("/"):
        connect_args["host"] = unix_socket_host
        tcp_host = None
        port = None
    else:
        # TCP URL
        if hostpart and ":" in hostpart:
            tcp_host, port_s = hostpart.rsplit(":", 1)
            port: int | None = int(port_s) if port_s.isdigit() else None
        else:
            tcp_host = hostpart or "localhost"
            port = None

    url = URL.create(
        drivername=scheme,
        username=username,
        password=password,
        host=tcp_host if not connect_args else None,
        port=port if not connect_args else None,
        database=database,
        query=query or None,
    )
    return url, connect_args


_engine_url, _connect_args = _parse_engine_config(settings.DATABASE_URL)

engine = create_async_engine(
    _engine_url,
    echo=settings.ENVIRONMENT == "development",
    pool_size=20,
    max_overflow=10,
    connect_args=_connect_args,
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
