from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT / ".env", extra="ignore")

    openai_api_key: str | None = None
    openai_embed_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o-mini"
    db_path: str = "./data/inbox.db"
    ingest_workers: int = 2
    chunk_target_tokens: int = 400
    chunk_overlap_tokens: int = 60
    retrieval_top_k: int = 5
    abstain_threshold: float = 0.25
    fetch_timeout_s: float = 10.0
    fetch_max_bytes: int = 2_097_152
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
