from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "global"
    DATABASE_URL: str = ""
    FIREBASE_PROJECT_ID: str = ""
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173", "https://project-b41c0c0d-6eea-4e9d-a78.web.app"]
    ENVIRONMENT: str = "development"
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_USE_VERTEX_AI: bool = True
    VERTEX_AI_LOCATION: str = "global"
    DOCUMENT_AI_LOCATION: str = "us"
    DOCUMENT_AI_PROCESSOR_ID: str = ""
    DOCUMENT_AI_PROCESSOR_VERSION: str = ""

    # AI configuration
    AI_GCS_BUCKET: str = "retailsg-ai-artifacts"
    AI_SYNC_TIMEOUT_SECONDS: int = 15
    AI_ASYNC_TIMEOUT_SECONDS: int = 120

    # Multica Configuration
    MULTICA_ENDPOINT_URL: str = ""

    # Snowflake configuration
    SNOWFLAKE_ACCOUNT: str = ""
    SNOWFLAKE_USER: str = ""
    SNOWFLAKE_PASSWORD: str = ""
    SNOWFLAKE_DATABASE: str = ""
    SNOWFLAKE_SCHEMA: str = "PUBLIC"
    SNOWFLAKE_WAREHOUSE: str = "COMPUTE_WH"
    SNOWFLAKE_ROLE: str = "ACCOUNTADMIN"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def validate_production_config(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if not self.DATABASE_URL:
                raise ValueError("DATABASE_URL must be set in production")
            if not self.GCP_PROJECT_ID:
                raise ValueError("GCP_PROJECT_ID must be set in production")
            if not self.FIREBASE_PROJECT_ID:
                raise ValueError("FIREBASE_PROJECT_ID must be set in production")
        return self


settings = Settings()
