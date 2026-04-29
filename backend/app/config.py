from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "global"
    DATABASE_URL: str = ""  # Legacy — kept for migration tooling

    # TiDB Cloud (MySQL-compatible) — used for the inventory ledger and any
    # other relational/analytical workloads. Format examples:
    #   mysql+asyncmy://user:pass@host:4000/db?ssl=true
    #   sqlite+aiosqlite:///./local.sqlite   (for local dev only)
    # Leave empty in environments that do not yet need the TiDB layer; routes
    # gated on it will return 503 / no-op gracefully.
    TIDB_DATABASE_URL: str = ""

    # Optional CA bundle path for TLS to TiDB Cloud. The python:3.14-slim base
    # image ships system roots at /etc/ssl/certs/ca-certificates.crt; on macOS
    # dev machines you may need to set this explicitly.
    TIDB_SSL_CA: str = ""
    FIREBASE_PROJECT_ID: str = ""
    FIRESTORE_EMULATOR_HOST: str = ""
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173", "https://victoriaensoapp.web.app"]
    ENVIRONMENT: str = "development"
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_USE_VERTEX_AI: bool = True
    DEEPSEEK_API_KEY: str = ""
    VERTEX_AI_LOCATION: str = "global"
    DOCUMENT_AI_LOCATION: str = "us"
    DOCUMENT_AI_PROCESSOR_ID: str = ""
    DOCUMENT_AI_PROCESSOR_VERSION: str = ""

    # AI configuration
    AI_GCS_BUCKET: str = "victoriaensoapp-ai-artifacts"
    AI_SYNC_TIMEOUT_SECONDS: int = 15
    AI_ASYNC_TIMEOUT_SECONDS: int = 120

    # Identity allowlist for the master-data "Publish to POS" action. The two
    # named owners (Craig and Irina) are the only people who should be able to
    # write a price into Firestore directly from the Master Data page.
    # Override in prod with the JSON-array form, e.g.
    #   MASTER_DATA_PUBLISHER_EMAILS='["craig@victoriaenso.com","irina@victoriaenso.com","new@..."]'
    MASTER_DATA_PUBLISHER_EMAILS: List[str] = [
        "craig@victoriaenso.com",
        "irina@victoriaenso.com",
    ]

    # Multica Configuration
    MULTICA_ENDPOINT_URL: str = ""
    OPENCLAW_WEBHOOK_URL: str = ""

    # Snowflake configuration
    SNOWFLAKE_ACCOUNT: str = ""         # e.g. "xy12345.ap-southeast-1"
    SNOWFLAKE_USER: str = ""
    SNOWFLAKE_PASSWORD: str = ""
    SNOWFLAKE_DATABASE: str = "RETAILSG"
    SNOWFLAKE_SCHEMA: str = "ANALYTICS"
    SNOWFLAKE_WAREHOUSE: str = "RETAILSG_WH"
    SNOWFLAKE_ROLE: str = "RETAILSG_ROLE"
    SNOWFLAKE_ETL_SCHEMA: str = "ETL"   # staging schema used by ETL jobs

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def validate_production_config(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if not self.GCP_PROJECT_ID:
                raise ValueError("GCP_PROJECT_ID must be set in production")
            if not self.FIREBASE_PROJECT_ID:
                raise ValueError("FIREBASE_PROJECT_ID must be set in production")
        return self


settings = Settings()
