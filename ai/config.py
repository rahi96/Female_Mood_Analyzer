from pydantic import field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "Pulse_E"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    BACKEND_URL: str = "https://hard-hulky-diane.ngrok-free.dev/api/v1"
    BACKEND_ACCESS_TOKEN: str = ""
    LAB_REPORTS_URL: str = "https://overapprehensive-optatively-meri.ngrok-free.dev/api/v1/lab-reports"
    SKIN_SCANS_URL: str = "https://hard-hulky-diane.ngrok-free.dev/api/v1/skin-scans"
    CYCLE_ENGINE_PROFILE_URL: str = "https://overapprehensive-optatively-meri.ngrok-free.dev/api/v1/user-profile"
    CYCLE_ENGINE_SNAPSHOT_URL: str = "https://overapprehensive-optatively-meri.ngrok-free.dev/api/v1/snapshot/3"
    CYCLE_CALENDAR_INPUTS_URL: str = "https://api.fightthenumber.com/api/v1/cycle-calendar-inputs"
    HEALTH_TRENDS_HEALTH_LOGS_URL: str = "https://overapprehensive-optatively-meri.ngrok-free.dev/api/v1/health-logs"
    CYCLE_ENGINE_ACCESS_TOKEN: str = ""
    BACKEND_REFRESH_TOKEN: str = ""
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-opus-4-7"
    CHAT_HISTORY_DB_PATH: str = "data/chat_history.db"
    FREE_CHAT_LIMIT: int = 5
    PREMIUM_CHAT_LIMIT: int = 100
    SUBSCRIPTION_STATUS_PATH: str = "/user/subscription/{user_id}"

    # MySQL Database
    MYSQL_HOST: str = ""
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = ""
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = ""

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


def snapshot_url_for(user_id=None) -> str:
    """Build the health-snapshot URL for a specific user.

    The configured CYCLE_ENGINE_SNAPSHOT_URL may end with a placeholder user id
    (e.g. .../snapshot/2). That trailing numeric id is stripped and replaced
    with the given user_id so each request targets the correct user. When
    user_id is None the configured URL is returned unchanged as a fallback.
    """
    configured = settings.CYCLE_ENGINE_SNAPSHOT_URL.rstrip("/")
    if user_id is None:
        return configured
    base, _, last = configured.rpartition("/")
    if base and last.isdigit():
        configured = base
    return f"{configured}/{user_id}"


def user_id_from_profile(profile) -> int | None:
    """Extract a user id from a backend profile payload of varying shapes."""
    paths = (
        ("id",),
        ("user_id",),
        ("user", "id"),
        ("data", "id"),
        ("data", "user_id"),
        ("data", "user", "id"),
    )
    for path in paths:
        node = profile
        for key in path:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                node = None
                break
        if isinstance(node, int):
            return node
        if isinstance(node, str) and node.isdigit():
            return int(node)
    return None
