"""Environment configuration; imports never contact external services."""

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FOODBRIDGE_",
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True,
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    environment: str = "local"
    database_url: str = "postgresql+psycopg://foodbridge:foodbridge_local@localhost:5432/foodbridge"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    enable_local_intake_demo: bool = False
    extraction_provider: Literal[
        "auto", "rules", "openai", "gemini", "anthropic", "openai_compatible"
    ] = "auto"
    extraction_model: str | None = None
    extraction_api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "FOODBRIDGE_OPENAI_API_KEY"),
        repr=False,
        exclude=True,
    )
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GEMINI_API_KEY", "GOOGLE_API_KEY", "FOODBRIDGE_GEMINI_API_KEY"
        ),
        repr=False,
        exclude=True,
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "FOODBRIDGE_ANTHROPIC_API_KEY"),
        repr=False,
        exclude=True,
    )
    extraction_base_url: str | None = None
    extraction_response_format: Literal["json_schema", "json_object"] = "json_schema"
    extraction_timeout_s: float = Field(default=8, gt=0, le=20)
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    @model_validator(mode="after")
    def safe_modes(self) -> Self:
        if self.enable_local_intake_demo and self.environment != "local":
            raise ValueError("local intake demo cannot be enabled outside local development")
        keys = {
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
            "anthropic": self.anthropic_api_key,
        }
        # Resolve once at startup. Never probe keys or fail over to another vendor.
        if self.extraction_provider == "auto":
            configured = [name for name, key in keys.items() if key]
            if self.extraction_api_key or len(configured) > 1:
                raise ValueError("Set FOODBRIDGE_EXTRACTION_PROVIDER when keys are ambiguous")
            self.extraction_provider = configured[0] if configured else "rules"
        if self.extraction_provider != "rules":
            self.extraction_api_key = self.extraction_api_key or keys.get(self.extraction_provider)
            if (
                not self.extraction_api_key
                or not self.extraction_api_key.get_secret_value().strip()
            ):
                raise ValueError("Selected extraction provider requires a server API key")
            defaults = {
                "openai": "gpt-4.1-mini",
                "gemini": "gemini-2.5-flash",
                "anthropic": "claude-sonnet-4-5",
            }
            self.extraction_model = self.extraction_model or defaults.get(self.extraction_provider)
            if not self.extraction_model or not self.extraction_model.strip():
                raise ValueError("Selected extraction provider requires an explicit model")
        if self.extraction_provider == "openai_compatible":
            url = urlsplit(self.extraction_base_url or "")
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "OpenAI-compatible base URL must be HTTPS without credentials/query"
                )
        elif self.extraction_base_url:
            raise ValueError("Custom base URL requires provider=openai_compatible")
        if self.oidc_jwks_url and not self.oidc_jwks_url.startswith("https://"):
            raise ValueError("OIDC JWKS must use HTTPS")
        return self
