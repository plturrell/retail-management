from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # GCP Project: project-b41c0c0d-6eea-4e9d-a78 (561509133799)
    GCP_PROJECT_ID: str = "project-b41c0c0d-6eea-4e9d-a78"
    DATABASE_URL: str = "postgresql+asyncpg://retailsg:retailsg@localhost:5432/retailsg"
    FIREBASE_PROJECT_ID: str = "project-b41c0c0d-6eea-4e9d-a78"
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    ENVIRONMENT: str = "development"
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    GEMINI_API_KEY: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
