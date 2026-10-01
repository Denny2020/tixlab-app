from pydantic_settings import BaseSettings, SettingsConfigDict

# Only for local docker compose and tests. In Kubernetes both values come from a Secret,
# and the pods won't start without it.
LOCAL_ONLY = "local-dev-only-change-me"


class Settings(BaseSettings):
    """All settings come from TIXLAB_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="TIXLAB_")

    database_url: str = "postgresql+psycopg://tixlab:tixlab@localhost:5432/tixlab"
    valkey_url: str = "redis://localhost:6379/0"
    hold_ttl_seconds: int = 600
    email_queue: str = "tixlab:queue:emails"
    report_email: str = "ops@tixlab.local"
    # Public base URL, used for ticket links in emails.
    public_url: str = "http://localhost:8088"
    # Set by the deployment to the image tag, so canaries are visible in the UI.
    version: str | None = None

    # Waiting room: once a drop opens, admit `admit_batch` fans at once, then this many per second.
    admit_per_second: float = 5.0
    admit_batch: int = 20
    queue_pass_ttl_seconds: int = 900

    # Secrets
    signing_key: str = LOCAL_ONLY  # HMAC key for tickets and queue passes
    organizer_token: str = LOCAL_ONLY  # bearer token for /api/admin/*
    # Set in Kubernetes: refuse to start with the local-only defaults (fail closed).
    require_secrets: bool = False

    # Load-test bots book with this domain; they get no confirmation emails.
    bot_email_domain: str = "bots.example.com"


settings = Settings()
