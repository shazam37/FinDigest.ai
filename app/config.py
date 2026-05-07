from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # === LLM ===
    GROQ_API_KEY: str = "placeholder"

    # === Search ===
    TAVILY_API_KEY: str = "placeholder"

    # === Email recipient ===
    RECIPIENT_EMAIL: str = "user@example.com"
    SENDER_EMAIL: str = "sender@example.com"

    # === Google OAuth ===
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None
    GOOGLE_CREDENTIALS_PATH: Optional[str] = "credentials/google_credentials.json"
    GOOGLE_TOKEN_PATH: str = "credentials/token.json"

    # === Timezone ===
    USER_TIMEZONE: str = "Asia/Kolkata"

    # === Agent behaviour ===
    LOOKBACK_HOURS: int = 24
    MAX_STORIES: int = 8
    MIN_STORIES_BEFORE_SEND: int = 3
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # === Phase 1: PostgreSQL ===
    DATABASE_URL: str = "postgresql://localhost:5432/fintech_agent"

    # === Phase 1: Alert agent ===
    ALERT_URGENCY_THRESHOLD: int = 8
    ALERT_POLL_HOURS: int = 2

    # === Phase 1: Story memory / deduplication ===
    SIMILARITY_THRESHOLD: float = 0.85
    MEMORY_LOOKBACK_DAYS: int = 7

    # === Phase 2: Feedback / preference learning ===
    # Minimum number of feedback signals before preference profile is used
    MIN_FEEDBACK_FOR_PROFILE: int = 5
    # How many recent feedback signals to consider for the profile
    FEEDBACK_WINDOW: int = 50
    # Base URL of the deployed app — used to generate feedback links in emails
    APP_BASE_URL: str = "http://localhost:8000"

    # === Phase 2: Watchlist ===
    # Max watchlist entities per user
    MAX_WATCHLIST_ENTITIES: int = 20

    # === Phase 2: Weekly synthesis ===
    # Day of week for Friday synthesis (0=Mon … 6=Sun)
    SYNTHESIS_DAY_OF_WEEK: str = "fri"
    SYNTHESIS_HOUR: int = 8   # 8 AM — before the daily digest

    # === Phase 2: Sentiment tracking ===
    # Rolling window (days) for sentiment velocity tracking
    SENTIMENT_WINDOW_DAYS: int = 30
    # Absolute sentiment score shift that triggers a signal alert
    SENTIMENT_ALERT_DELTA: float = 0.3


    # === Phase 3: Slack delivery ===
    SLACK_BOT_TOKEN: Optional[str] = None        # xoxb-...
    SLACK_CHANNEL_ID: Optional[str] = None       # C0XXXXXXX

    # === Phase 3: Telegram bot ===
    TELEGRAM_BOT_TOKEN: Optional[str] = None     # From @BotFather
    TELEGRAM_CHAT_ID: Optional[str] = None       # Your personal chat ID

    # === Phase 3: LangSmith observability ===
    LANGSMITH_API_KEY: Optional[str] = None      # From smith.langchain.com
    LANGSMITH_PROJECT: str = "fintech-agent"
    # Health report sent every Monday morning
    HEALTH_REPORT_HOUR: int = 8

    # === Phase 3: Deep-dive research ===
    RESEARCH_MAX_SEARCHES: int = 15
    RESEARCH_MAX_STORIES: int = 25

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()