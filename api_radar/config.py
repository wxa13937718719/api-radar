from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./api_radar.db"
    log_level: str = "INFO"
    request_timeout_seconds: float = 30.0
    llm_enabled: bool = False
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str | None = None
    llm_model: str = "llama3.2"
    llm_timeout_seconds: float = 45.0
    llm_max_tokens: int = 900
    llm_disable_reasoning: bool = False

    model_config = SettingsConfigDict(
        env_prefix="API_RADAR_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
