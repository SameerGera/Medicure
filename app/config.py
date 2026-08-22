from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_base_url: str = "http://localhost:8000"

    database_url: str = "sqlite:///./medicure.db"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = "whatsapp:+14155238886"


@lru_cache
def get_settings() -> Settings:
    return Settings()
