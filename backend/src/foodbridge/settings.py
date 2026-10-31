"""Environment configuration; imports never contact external services."""

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FOODBRIDGE_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    environment: str = "local"
    database_url: str = "postgresql+psycopg://foodbridge:foodbridge_local@localhost:5432/foodbridge"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    enable_local_intake_demo: bool = False
    extraction_provider: Literal["rules", "openai"] = "rules"
    extraction_model: str | None = None
    extraction_api_key: SecretStr | None = None
    extraction_timeout_s: float = Field(default=8, gt=0, le=20)
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    @model_validator(mode="after")
    def safe_modes(self) -> Self:
        if self.enable_local_intake_demo and self.environment != "local":
            raise ValueError("local intake demo cannot be enabled outside local development")
        if self.extraction_provider == "openai" and not (
            self.extraction_model and self.extraction_api_key
        ):
            raise ValueError("OpenAI extraction requires an explicit model and server API key")
        if self.oidc_jwks_url and not self.oidc_jwks_url.startswith("https://"):
            raise ValueError("OIDC JWKS must use HTTPS")
        return self
