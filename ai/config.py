from pydantic import field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "Pulse_E"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    BACKEND_URL: str = "https://hard-hulky-diane.ngrok-free.dev/api/v1"
    BACKEND_ACCESS_TOKEN: str = ""
    LAB_REPORTS_URL: str = "https://overapprehensive-optatively-meri.ngrok-free.dev/api/v1/lab-reports"
    BACKEND_REFRESH_TOKEN: str = ""
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-opus-4-7"
    CHAT_HISTORY_DB_PATH: str = "data/chat_history.db"
    FREE_CHAT_LIMIT: int = 5
    PREMIUM_CHAT_LIMIT: int = 100
    SUBSCRIPTION_STATUS_PATH: str = "/user/subscription/{user_id}"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production", "false", "0", "no", "off"}:
                return False
            if normalized in {"debug", "dev", "development", "true", "1", "yes", "on"}:
                return True
        return value
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
