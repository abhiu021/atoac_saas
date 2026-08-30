"""Central configuration, loaded from environment (.env supported)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _normalize_db_url(url: str) -> str:
    # Many hosts (Render, Heroku, Neon) hand out the legacy "postgres://" scheme,
    # which SQLAlchemy 2.0 rejects — rewrite it to the "postgresql://" it expects.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


class Settings:
    # Core — set DATABASE_URL to a managed Postgres for persistent storage; blank
    # (default) uses a local SQLite file (ephemeral on most hosts).
    DATABASE_URL: str = _normalize_db_url(os.getenv("DATABASE_URL", "sqlite:///./atoac.db"))
    JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me-in-production")
    JWT_EXPIRY_HOURS: int = int(os.getenv("JWT_EXPIRY_HOURS", "2"))
    JWT_ALGORITHM: str = "HS256"

    # Razorpay — blank means mock mode
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

    # Optional LLM framing (Google Gemini, free tier) — blank means templated fallback
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    # Fast, free default. Override with GEMINI_MODEL (e.g. gemini-3.1-flash-lite).
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

    # Login rate limiting
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 5

    # Inventory reservation
    RESERVATION_TTL_MINUTES: int = int(os.getenv("RESERVATION_TTL_MINUTES", "15"))
    RESTOCK_LEAD_DAYS: int = int(os.getenv("RESTOCK_LEAD_DAYS", "10"))

    @property
    def razorpay_live(self) -> bool:
        return bool(self.RAZORPAY_KEY_ID and self.RAZORPAY_KEY_SECRET)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.GEMINI_API_KEY)


settings = Settings()
