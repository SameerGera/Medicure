import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_base_url: str = ""
    database_url: str = ""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = "whatsapp:+14155238886"

    telegram_bot_token: str = ""

    @field_validator("public_base_url", mode="before")
    @classmethod
    def validate_public_base_url(cls, v: str | None) -> str:
        if not v or not str(v).strip():
            vercel_url = os.environ.get("VERCEL_URL", "")
            return f"https://{vercel_url}" if vercel_url else "http://localhost:8000"
        url = str(v).strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            return f"https://{url}"
        return url

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str | None) -> str:
        is_serverless = bool(
            os.environ.get("VERCEL")
            or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
            or os.environ.get("NOW_REGION")
        )
        if not v or not str(v).strip():
            return "sqlite:////tmp/medicure.db" if is_serverless else "sqlite:///./medicure.db"

        url = str(v).strip()
        # Coerce legacy postgres:// to modern postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)

        # On Vercel serverless, root directory is read-only. Redirect relative sqlite to /tmp
        if is_serverless and url.startswith("sqlite") and not url.startswith("sqlite:////tmp"):
            return "sqlite:////tmp/medicure.db"

        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
