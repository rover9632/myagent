from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM / vLLM
    llm_base_url: str = Field(default="http://127.0.0.1:8000/v1")
    llm_api_key: str = Field(default="EMPTY")
    llm_model: str = Field(default="Qwen/Qwen3-8B")
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=2048, ge=1, le=32768)
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=10)

    # Tavily
    tavily_api_key: str = Field(default="")
    tavily_max_results: int = Field(default=5, ge=1, le=20)

    # Docker sandbox
    sandbox_image: str = Field(default="agent-sandbox:py312")
    sandbox_workspace_root: Path = Field(default=Path("./data/workspaces"))
    sandbox_default_timeout_seconds: int = Field(default=30, ge=1)
    sandbox_max_timeout_seconds: int = Field(default=120, ge=1)
    sandbox_memory: str = Field(default="512m")
    sandbox_cpus: float = Field(default=1.0, gt=0)
    sandbox_pids_limit: int = Field(default=64, ge=16)
    sandbox_max_output_bytes: int = Field(default=12000, ge=1024)
    # Delete thread workspaces untouched for this many days; 0 disables cleanup.
    sandbox_workspace_ttl_days: int = Field(default=7, ge=0)

    # FastAPI
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8061, ge=1, le=65535)
    log_level: str = Field(default="INFO")
    # Bearer token for /v1 endpoints. Empty string disables auth (warned at startup).
    api_token: str = Field(default="")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.sandbox_workspace_root = settings.sandbox_workspace_root.resolve()
    return settings
