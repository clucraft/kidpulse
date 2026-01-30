"""Configuration management for KidPulse."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def get_bool(key: str, default: bool = False) -> bool:
    """Get boolean from environment variable."""
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


@dataclass
class PlaygroundConfig:
    """Playground authentication config."""
    email: str
    password: str
    organization: str
    base_url: str = "https://app.tryplayground.com"


@dataclass
class NtfyConfig:
    """NTFY notification config."""
    enabled: bool
    server: str
    topic: str

    @property
    def url(self) -> str:
        return f"{self.server}/{self.topic}"


@dataclass
class TelegramConfig:
    """Telegram notification config."""
    enabled: bool
    bot_token: str
    chat_id: str


@dataclass
class AIConfig:
    """AI parsing configuration."""
    enabled: bool
    provider: str  # "ollama" or "openai"
    ollama_url: str
    ollama_model: str
    openai_api_key: str
    openai_model: str


@dataclass
class Config:
    """Main application configuration."""
    playground: PlaygroundConfig
    ntfy: NtfyConfig
    telegram: TelegramConfig
    ai: AIConfig
    summary_time: str
    scrape_interval: int
    timezone: str
    debug: bool

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            playground=PlaygroundConfig(
                email=os.getenv("PLAYGROUND_EMAIL", ""),
                password=os.getenv("PLAYGROUND_PASSWORD", ""),
                organization=os.getenv("PLAYGROUND_ORGANIZATION", ""),
            ),
            ntfy=NtfyConfig(
                enabled=get_bool("NTFY_ENABLED"),
                server=os.getenv("NTFY_SERVER", "https://ntfy.sh"),
                topic=os.getenv("NTFY_TOPIC", "kidpulse"),
            ),
            telegram=TelegramConfig(
                enabled=get_bool("TELEGRAM_ENABLED"),
                bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
                chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            ),
            ai=AIConfig(
                enabled=get_bool("AI_ENABLED"),
                provider=os.getenv("AI_PROVIDER", "ollama"),
                ollama_url=os.getenv("OLLAMA_URL", "http://host.docker.internal:11434"),
                ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
                openai_api_key=os.getenv("OPENAI_API_KEY", ""),
                openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            ),
            summary_time=os.getenv("SUMMARY_TIME", "17:00"),
            scrape_interval=int(os.getenv("SCRAPE_INTERVAL", "30")),
            timezone=os.getenv("TZ", "America/New_York"),
            debug=get_bool("DEBUG"),
        )

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if not self.playground.email:
            errors.append("PLAYGROUND_EMAIL is required")
        if not self.playground.password:
            errors.append("PLAYGROUND_PASSWORD is required")

        if self.ntfy.enabled and not self.ntfy.topic:
            errors.append("NTFY_TOPIC is required when NTFY is enabled")

        if self.telegram.enabled:
            if not self.telegram.bot_token:
                errors.append("TELEGRAM_BOT_TOKEN is required when Telegram is enabled")
            if not self.telegram.chat_id:
                errors.append("TELEGRAM_CHAT_ID is required when Telegram is enabled")

        return errors
