from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    environment: str = "development"  # development | staging | production
    port: int = 8000

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Anthropic (Claude)
    anthropic_api_key: str = ""

    # OpenSanctions
    opensanctions_api_key: str = ""

    # Google Custom Search (adverse media)
    google_cse_api_key: str = ""  # Google API key
    google_cse_id: str = ""       # Custom Search Engine ID


settings = Settings()
