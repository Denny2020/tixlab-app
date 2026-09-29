from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from TIXLAB_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="TIXLAB_")

    database_url: str = "postgresql+psycopg://tixlab:tixlab@localhost:5432/tixlab"
    valkey_url: str = "redis://localhost:6379/0"
    hold_ttl_seconds: int = 600
    email_queue: str = "tixlab:queue:emails"
    report_email: str = "ops@tixlab.local"
    # Set by the deployment to the image tag, so canaries are visible in the UI.
    version: str | None = None


settings = Settings()
