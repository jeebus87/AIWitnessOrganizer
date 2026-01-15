"""Application configuration using Pydantic Settings"""
from functools import lru_cache
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    app_name: str = "AIWitnessFinder"
    environment: str = "development"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # Database (raw URL from env, will be transformed)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/aiwitnessfinder"

    @property
    def database_url_async(self) -> str:
        """Get database URL formatted for asyncpg"""
        url = self.database_url
        # Railway uses postgres:// or postgresql://, but asyncpg needs postgresql+asyncpg://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Clio OAuth
    clio_client_id: str = ""
    clio_client_secret: str = ""
    clio_redirect_uri: str = "http://localhost:8000/auth/callback"
    clio_base_url: str = "https://app.clio.com"
    clio_api_version: str = "v4"
    clio_rate_limit: int = 50  # requests per minute

    # AWS Bedrock
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-sonnet-4-5-20250929-v1:0"

    # Firebase
    firebase_project_id: Optional[str] = None
    firebase_private_key_id: Optional[str] = None
    firebase_private_key: Optional[str] = None
    firebase_client_email: Optional[str] = None
    firebase_client_id: Optional[str] = None

    # Stripe
    stripe_secret_key: Optional[str] = None
    stripe_publishable_key: Optional[str] = None
    stripe_webhook_secret: Optional[str] = None

    # Encryption
    fernet_key: str = ""

    # CORS
    frontend_url: str = "http://localhost:3000"
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    @property
    def clio_authorize_url(self) -> str:
        return f"{self.clio_base_url}/oauth/authorize"

    @property
    def clio_token_url(self) -> str:
        return f"{self.clio_base_url}/oauth/token"

    @property
    def clio_api_url(self) -> str:
        return f"{self.clio_base_url}/api/{self.clio_api_version}"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
