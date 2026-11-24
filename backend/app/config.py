from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    app_name: str = "Stacks"
    debug: bool = False
    secret_key: str = "changeme-in-production"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Database
    database_url: str = "postgresql+asyncpg://stacks:stacks@db:5432/stacks"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # S3 / Object Storage
    s3_bucket: str = "stacks-files"
    s3_region: str = "us-east-1"
    s3_endpoint_url: Optional[str] = None  # for S3-compatible services (MinIO etc.)
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    s3_presigned_url_expiry: int = 900  # 15 minutes

    # Auth
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    algorithm: str = "HS256"

    # LTI
    lti_private_key_storage: str = "database"  # 'database' | 'aws_secrets'

    # Z39.50 / YAZ sidecar gateway
    yaz_gateway_url: str = "http://yaz:8080"

    # Email
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    email_from: str = "noreply@example.com"

    @model_validator(mode="after")
    def _require_secret_key(self) -> "Settings":
        # Tokens are signed with SECRET_KEY: refuse to start with an empty or
        # placeholder key outside debug mode
        if not self.secret_key.strip():
            raise ValueError("SECRET_KEY must be set (see .env.example)")
        if not self.debug and self.secret_key == "changeme-in-production":
            raise ValueError("SECRET_KEY is still the placeholder; set a real value")
        return self

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
