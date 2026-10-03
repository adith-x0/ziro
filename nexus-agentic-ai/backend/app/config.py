from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """NEXUS Application Configuration Settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General Environment
    environment: str = Field(default="development", description="Runtime environment")
    debug: bool = Field(default=True, description="Debug mode flag")
    log_level: str = Field(default="INFO", description="Logging level")
    service_name: str = Field(default="nexus-backend", description="Service identifier")
    service_version: str = Field(default="0.1.0", description="Semantic service version")

    # Network / Host
    host: str = Field(default="0.0.0.0", description="Bind host")
    port: int = Field(default=8000, description="Bind port")
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins",
    )

    # Persistence & Caching
    database_url: str = Field(
        default="postgresql+asyncpg://nexus_user:nexus_secret_pass@localhost:5432/nexus_db",
        description="Async PostgreSQL connection URL",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # LLM Settings (Google Gemini)
    gemini_api_key: str = Field(default="", description="Google GenAI API Key")
    gemini_flash_model: str = Field(default="gemini-2.5-flash", description="Gemini Flash Model")
    gemini_pro_model: str = Field(default="gemini-2.5-pro", description="Gemini Pro Model")

    # Safety & Simulation Parameters
    flood_surge_threshold_percent: float = Field(
        default=15.0,
        description="Sensor threshold percentage delta to trigger replanning",
    )
    safety_gate_strict_mode: bool = Field(
        default=True,
        description="Enforce strict deterministic interception of Tier 3/4 actions",
    )
    verification_confidence_threshold: float = Field(
        default=0.80,
        description="Minimum confidence score required to mark incident as verified",
    )
    evidence_staleness_max_hours: float = Field(
        default=2.0,
        description="Maximum age in hours before empirical evidence is treated as stale",
    )
    safety_evidence_staleness_max_seconds: float = Field(
        default=1800.0,
        description=(
            "Tactical freshness threshold in seconds for Safety Agent "
            "pre-execution gatekeeping (stricter than verification)"
        ),
    )


settings = Settings()
