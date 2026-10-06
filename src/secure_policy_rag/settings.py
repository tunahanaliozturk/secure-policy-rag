"""Configuration from environment variables prefixed ``SPR_``. docs/operations.md has the full table."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from secure_policy_rag.model import Effort
from secure_policy_rag.store import Retriever
from secure_policy_rag.telemetry import TraceExporter

MIN_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPR_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://spr_app@127.0.0.1:55440/policies"
    """The application's connection: the spr_app role, which row-level security applies to."""
    admin_database_url: str | None = None
    """Only for ``spr migrate`` and ``spr ingest``. The API never needs it."""
    app_db_password: SecretStr | None = None
    """Set on the spr_app role by ``spr migrate``."""

    token_secret: SecretStr | None = None
    """Signs and verifies bearer tokens. At least 32 bytes."""
    token_secret_previous: SecretStr | None = None
    """Still accepted for verification during a rotation, never used to sign."""

    model_provider: Literal["anthropic", "scripted"] = "anthropic"
    model: str = "claude-sonnet-5-5"
    effort: Effort = "medium"

    embedder: Literal["fastembed", "hashing"] = "fastembed"
    model_cache_dir: Path | None = None

    retrievers: Literal["hybrid", "vector", "lexical"] = "hybrid"
    """Which rankings feed retrieval. docs/evaluation.md has the measured difference on this corpus."""
    allowed_link_hosts: str = "intranet.bank.example"
    """Comma-separated. An answer may only contain links to these hosts, and only links its sources contain."""
    top_k: int = 5
    rate_limit_per_minute: int = 20

    trace_exporter: TraceExporter = "console"
    log_level: str = "INFO"

    def retriever_set(self) -> frozenset[Retriever]:
        return frozenset({"lexical", "vector"}) if self.retrievers == "hybrid" else frozenset({self.retrievers})

    def link_hosts(self) -> frozenset[str]:
        return frozenset(h.strip().lower() for h in self.allowed_link_hosts.split(",") if h.strip())

    def token_secrets(self) -> list[bytes]:
        """Newest first. Refuses to hand out a missing or short secret rather than let the API start with one."""
        secrets = [s.get_secret_value().encode() for s in (self.token_secret, self.token_secret_previous) if s]
        if not secrets or self.token_secret is None:
            raise ValueError("SPR_TOKEN_SECRET is not set")
        if any(len(s) < MIN_SECRET_BYTES for s in secrets):
            raise ValueError(f"token secrets must be at least {MIN_SECRET_BYTES} bytes")
        return secrets
