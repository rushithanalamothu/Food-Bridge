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
    enable_intake_metrics: bool = False
    ai_provider: Literal["auto", "rules", "openai", "gemini", "anthropic", "openai_compatible"] = (
        Field(
            default="auto",
            validation_alias=AliasChoices(
                "FOODBRIDGE_AI_PROVIDER", "FOODBRIDGE_EXTRACTION_PROVIDER"
            ),
        )
    )
    ai_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FOODBRIDGE_AI_MODEL", "FOODBRIDGE_EXTRACTION_MODEL"),
    )
    ai_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        exclude=True,
        validation_alias=AliasChoices("FOODBRIDGE_AI_API_KEY", "FOODBRIDGE_EXTRACTION_API_KEY"),
    )
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
    ai_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FOODBRIDGE_AI_BASE_URL", "FOODBRIDGE_EXTRACTION_BASE_URL"),
    )
    ai_response_format: Literal["json_schema", "json_object"] = Field(
        default="json_schema",
        validation_alias=AliasChoices(
            "FOODBRIDGE_AI_RESPONSE_FORMAT", "FOODBRIDGE_EXTRACTION_RESPONSE_FORMAT"
        ),
    )
    ai_timeout_s: float = Field(
        default=8,
        gt=0,
        le=20,
        validation_alias=AliasChoices("FOODBRIDGE_AI_TIMEOUT_S", "FOODBRIDGE_EXTRACTION_TIMEOUT_S"),
    )
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    @model_validator(mode="after")
    def safe_modes(self) -> Self:
        if self.enable_local_intake_demo and self.environment != "local":
            raise ValueError("local intake demo cannot be enabled outside local development")
        if self.enable_intake_metrics and self.environment != "local":
            raise ValueError(
                "intake metrics endpoint is local-only; protect shared exports separately"
            )
        keys = {
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
            "anthropic": self.anthropic_api_key,
        }
        # Resolve once at startup. Never probe keys or fail over to another vendor.
        if self.ai_provider == "auto":
            configured = [name for name, key in keys.items() if key]
            if self.ai_api_key or len(configured) > 1:
                raise ValueError("Set FOODBRIDGE_AI_PROVIDER when keys are ambiguous")
            self.ai_provider = configured[0] if configured else "rules"
        if self.ai_provider != "rules":
            self.ai_api_key = self.ai_api_key or keys.get(self.ai_provider)
            if not self.ai_api_key or not self.ai_api_key.get_secret_value().strip():
                raise ValueError("Selected app AI provider requires a server API key")
            defaults = {
                "openai": "gpt-4.1-mini",
                "gemini": "gemini-2.5-flash",
                "anthropic": "claude-sonnet-4-5",
            }
            self.ai_model = self.ai_model or defaults.get(self.ai_provider)
            if not self.ai_model or not self.ai_model.strip():
                raise ValueError("Selected app AI provider requires an explicit model")
        if self.ai_provider == "openai_compatible":
            url = urlsplit(self.ai_base_url or "")
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
        elif self.ai_base_url:
            raise ValueError("Custom base URL requires provider=openai_compatible")
        if self.oidc_jwks_url and not self.oidc_jwks_url.startswith("https://"):
            raise ValueError("OIDC JWKS must use HTTPS")
        return self
