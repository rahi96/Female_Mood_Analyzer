from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "Pulse_E"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
