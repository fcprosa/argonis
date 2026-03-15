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


settings = Settings()
