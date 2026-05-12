from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "Pulse_E"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    BACKEND_URL: str = "https://pulse-helthcare-backend-1.onrender.com/api/v1"
    BACKEND_ACCESS_TOKEN: str = ""
    BACKEND_REFRESH_TOKEN: str = ""
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-opus-4-7"
    CHAT_HISTORY_DB_PATH: str = "data/chat_history.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
