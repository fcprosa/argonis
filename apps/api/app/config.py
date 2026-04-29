import json
import logging
from typing import Self
from uuid import UUID

from pydantic import (
    AliasChoices,
    Field,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.env_parse import sanitize_env_secret

logger = logging.getLogger(__name__)


def _parse_cors_origins_string(raw: str) -> list[str]:
    """Parse CORS_ORIGINS env: JSON array, comma-separated, or single URL."""
    s = (raw or "").strip()
    if not s:
        return ["http://localhost:3000"]
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                out = [str(x).strip() for x in parsed if str(x).strip()]
                return out if out else ["http://localhost:3000"]
        except json.JSONDecodeError:
            pass
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return parts if parts else ["http://localhost:3000"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    environment: str = "development"  # development | staging | production
    port: int = 8000

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUPABASE_SERVICE_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        ),
    )
    supabase_jwt_secret: str = ""  # For local JWT verification (HS256)

    # CORS — read as plain str so DotEnvSettingsSource does not json.loads() it
    cors_origins_raw: str = Field(
        default="http://localhost:3000,https://argonis.vercel.app",
        validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins_raw"),
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        return _parse_cors_origins_string(self.cors_origins_raw)

    # Anthropic (Claude)
    anthropic_api_key: str = ""

    # OpenSanctions
    opensanctions_api_key: str = ""

    # Serper.dev (adverse media search)
    serper_api_key: str = ""  # https://serper.dev — Google search API

    @field_validator(
        "anthropic_api_key",
        "opensanctions_api_key",
        "serper_api_key",
        mode="before",
    )
    @classmethod
    def _strip_secret_env_noise(cls, v: object) -> str:
        if v is None:
            return sanitize_env_secret(None)
        return sanitize_env_secret(str(v))

    # Redis (optional — for multi-instance rate limiting)
    redis_url: str = ""

    # Demo mode (GET + X-Demo-Mode header — see app.auth)
    demo_mode: bool = Field(default=False, validation_alias=AliasChoices("DEMO_MODE"))
    demo_org_id: str = Field(default="", validation_alias=AliasChoices("DEMO_ORG_ID"))
    demo_user_id: str = Field(default="", validation_alias=AliasChoices("DEMO_USER_ID"))

    @field_validator("demo_mode", mode="before")
    @classmethod
    def _coerce_demo_mode(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        return str(v).strip().lower() in ("true", "1", "yes")

    @model_validator(mode="after")
    def _validate_demo_ids(self) -> Self:
        if not self.demo_mode:
            return self
        for label, raw in (
            ("DEMO_ORG_ID", self.demo_org_id),
            ("DEMO_USER_ID", self.demo_user_id),
        ):
            val = (raw or "").strip()
            if not val:
                msg = (
                    f"{label} is required and must be a valid UUID when "
                    "DEMO_MODE=true"
                )
                logger.critical(msg)
                raise ValueError(msg)
            try:
                UUID(val)
            except ValueError as exc:
                logger.critical("%s is not a valid UUID: %s", label, raw)
                raise ValueError(
                    f"{label} must be a valid UUID when DEMO_MODE=true"
                ) from exc
        return self


settings = Settings()
