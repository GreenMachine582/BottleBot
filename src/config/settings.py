from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Secrets loaded from .env — never committed to git."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="BOTTLEBOT_", extra="ignore")

    # Discord webhook, in apprise's native format: discord://<webhook_id>/<webhook_token>
    # (take the id/token pair from the webhook URL Discord gives you)
    discord_webhook_url: str = ""

    # Optional extra apprise target, e.g. ntfy://ntfy.sh/bottlebot-deals
    ntfy_url: str = ""
