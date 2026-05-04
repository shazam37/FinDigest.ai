from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # === LLM ===
    GROQ_API_KEY: str

    # === Search ===
    TAVILY_API_KEY: str

    # === Email recipient ===
    RECIPIENT_EMAIL: str          # Where to send the digest
    SENDER_EMAIL: str             # Gmail address used to send

    # === Google OAuth (for Gmail + Calendar) ===
    # Either provide the JSON content directly (recommended for Render)
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None
    # Or a path to the credentials file (local dev)
    GOOGLE_CREDENTIALS_PATH: Optional[str] = "credentials/google_credentials.json"
    GOOGLE_TOKEN_PATH: str = "credentials/token.json"

    # === Timezone ===
    USER_TIMEZONE: str = "Asia/Kolkata"  # Change to your timezone

    # === Agent behaviour ===
    LOOKBACK_HOURS: int = 24          # How far back to search
    MAX_STORIES: int = 8              # Cap stories per digest
    MIN_STORIES_BEFORE_SEND: int = 3  # Don't send if fewer than this (likely an error)
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()