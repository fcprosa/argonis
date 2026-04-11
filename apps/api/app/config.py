from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    environment: str = "development"  # development | staging | production
    port: int = 8000

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_jwt_secret: str = ""  # For local JWT verification (HS256)

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Anthropic (Claude)
    anthropic_api_key: str = ""

    # OpenSanctions
    opensanctions_api_key: str = ""

    # Serper.dev (adverse media search)
    serper_api_key: str = ""  # https://serper.dev — Google search API

    # Redis (optional — for multi-instance rate limiting)
    redis_url: str = ""


settings = Settings()
