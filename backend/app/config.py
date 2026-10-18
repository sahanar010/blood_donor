from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.matching import Weights


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://bloodmatch:bloodmatch@localhost:5432/bloodmatch"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 8
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Hospital-local timezone, used for weekday/weekend radius and preferred hours.
    local_tz: str = "Asia/Kolkata"

    # CONFIGURABLE POLICY, NOT A MEDICAL DECISION. Set this to whatever your
    # blood bank / hospital's applicable rules say. Donor eligibility is
    # ultimately verified by the hospital (donors.verified + donation records).
    min_donation_interval_days: int = 90

    default_top_n: int = 3
    max_candidates: int = 200  # nearest N eligible donors that get scored

    # Ranking weights (soft signals only; hard eligibility rules are never weighted).
    w_distance: float = 0.30
    w_availability: float = 0.20
    w_reliability: float = 0.20
    w_travel: float = 0.10
    w_ml: float = 0.10
    w_rating: float = 0.10

    # Optional. Without it the realtime hub runs in-memory (single worker only).
    # With it: cross-worker fan-out + online presence. Falls back to in-memory if unreachable.
    redis_url: str | None = None

    # Serves a small realtime test page at /demo. Turn off in production.
    enable_demo_page: bool = True

    # Acceptance-probability model (train with: python -m app.ml.train). Missing model => rules only.
    ml_enabled: bool = True
    ml_model_path: str = str(Path(__file__).resolve().parents[1] / "models" / "acceptance_xgb.json")

    # Optional bootstrap admin, created at startup if both are set.
    admin_email: str | None = None
    admin_password: str | None = None

    @property
    def weights(self) -> Weights:
        return Weights(self.w_distance, self.w_availability, self.w_reliability,
                       self.w_travel, self.w_ml, self.w_rating)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
