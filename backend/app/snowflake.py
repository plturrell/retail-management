"""
Snowflake connection setup for RetailSG analytics/reporting.

Moved from database.py during the Firestore migration.
"""
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, Session

from app.config import settings

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
    """FastAPI dependency that yields a Snowflake SQLAlchemy session."""
    if not snowflake_session_factory:
        raise Exception("Snowflake is not configured.")
    db = snowflake_session_factory()
    try:
        yield db
    finally:
        db.close()
