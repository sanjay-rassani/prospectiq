"""Application settings.

Everything comes from the environment or a local .env file, never from code, and .env is
gitignored (spec section 18). Defaults are chosen so a fresh clone runs with no paid
credentials of any kind (FR-12, AC-1).
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["dev", "prod"] = "dev"
    debug: bool = True

    # Local-first: binding anywhere other than loopback requires authentication, which
    # does not exist yet (task P10-7).
    host: str = "127.0.0.1"
    port: int = 8000

    postgres_user: str = "prospectiq"
    postgres_password: str = "prospectiq"
    postgres_db: str = "prospectiq"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432

    # Separate database for tests so a test run can never truncate real prospects.
    test_postgres_db: str = "prospectiq_test"

    ollama_url: str = "http://127.0.0.1:11434"
    # Two models, two protocols. See spike/README.md and decisions D-06 and D-09.
    extraction_model: str = "numind/nuextract3:q4_k_m"
    generation_model: str = "qwen3.5:4b"
    # NuExtract's default 131072-token context would not fit the KV cache in available
    # RAM on this machine (decision D-11).
    llm_num_ctx: int = 8192
    llm_timeout_seconds: float = 600.0
    # Initial attempt + up to 2 retries (spec section 15.2).
    llm_max_attempts: int = 3
    # Cap page text before it reaches the model (task P3-4).
    llm_max_input_chars: int = 12000
    # Disable for environments without Ollama; seed/refresh still store snapshots.
    llm_enabled: bool = True
    # APScheduler in-process tick (Phase 8). Tests disable this.
    scheduler_enabled: bool = True

    # Politeness defaults for the fetcher (spec section 18).
    user_agent: str = "ProspectingEngine/0.1 (personal business research)"
    fetch_timeout_seconds: float = 30.0
    per_domain_delay_seconds: float = 5.0
    max_concurrent_fetches: int = 4

    log_level: str = Field(default="INFO")

    def _dsn(self, database: str) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=database,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return self._dsn(self.postgres_db)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def test_database_url(self) -> str:
        return self._dsn(self.test_postgres_db)


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is read once per process."""
    return Settings()
