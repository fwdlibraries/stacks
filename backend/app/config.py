import re

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    app_name: str = "Stacks"
    debug: bool = False
    secret_key: str = "changeme-in-production"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Database
    database_url: str = "postgresql+asyncpg://stacks:stacks@db:5432/stacks"
    sql_echo: bool = False  # log every SQL statement with its parameters (local debugging only)

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # S3 / Object Storage
    s3_bucket: str = "stacks-files"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None  # for S3-compatible services (MinIO etc.)
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_presigned_url_expiry: int = 900  # 15 minutes

    # Auth
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    algorithm: str = "HS256"
    # Failed password sign-ins allowed per account before it's paused, and for how
    # long (the pause starts at the first failure). Slows password guessing.
    login_max_failures: int = 10
    login_lockout_minutes: int = 15

    # LTI
    lti_private_key_storage: str = "database"  # 'database' | 'aws_secrets'
    # Where browsers reach Stacks (the frontend origin). Used for the LTI redirect_uri
    # and the tool URLs printed at registration. Dev: Vite on :5173 proxies /lti.
    public_base_url: str = "http://localhost:5173"
    # LMS origins allowed to show Stacks in an iframe (space-separated), e.g.
    # "https://lms.example.edu https://*.instructure.com". Empty: same-origin only.
    # Default for organizations that haven't set their own (organizations.settings).
    frame_ancestors: str = ""

    # Multi-tenancy. Requests are attributed to an organization by hostname
    # (organization_domains). Hosts that match none use DEFAULT_ORGANIZATION (a slug),
    # if set; with REQUIRE_KNOWN_HOST they're refused instead (hosted, multi-tenant).
    default_organization: str = ""
    require_known_host: bool = False

    # Allow plain-http identity providers for single sign-on (local testing with a mock
    # provider only). Deliberately separate from DEBUG, which a public dev site may have on.
    oidc_allow_http: bool = False

    # Encrypts stored credentials such as library API keys (Fernet key, see
    # `python -m app.cli generate-credentials-key`). Empty: derived from SECRET_KEY,
    # which then can't be rotated without re-entering those credentials.
    credentials_key: str = ""

    # Contact address sent to open metadata APIs (Crossref "polite pool"). Optional.
    metadata_contact_email: str = ""

    # Z39.50 / YAZ sidecar gateway
    yaz_gateway_url: str = "http://yaz:8080"

    # Email
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str = "noreply@example.com"

    @field_validator("frame_ancestors")
    @classmethod
    def _valid_frame_ancestors(cls, value: str) -> str:
        # Each entry ends up in a response header: allow only plain origins
        origin = re.compile(r"^https?://(\*\.)?[A-Za-z0-9.-]+(:\d{1,5})?$")
        sources = value.split()
        bad = [s for s in sources if not origin.match(s)]
        if bad:
            raise ValueError(f"FRAME_ANCESTORS entries must be origins like https://lms.example.edu: {bad}")
        return " ".join(sources)

    @property
    def frame_ancestors_policy(self) -> str:
        return " ".join(["frame-ancestors", "'self'", *self.frame_ancestors.split()])

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
