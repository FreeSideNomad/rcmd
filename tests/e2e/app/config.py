"""E2E Application Configuration."""

import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-e2e-testing")
    DATABASE_URL = os.environ.get(
        "E2E_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/commandbus",  # pragma: allowlist secret
    )
    DEBUG = os.environ.get("DEBUG", "1") == "1"


@dataclass
class WorkerConfig:
    """Worker configuration."""

    visibility_timeout: int = 30
    concurrency: int = 4
    poll_interval: float = 1.0
    batch_size: int = 10

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "visibility_timeout": self.visibility_timeout,
            "concurrency": self.concurrency,
            "poll_interval": self.poll_interval,
            "batch_size": self.batch_size,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerConfig":
        """Create from dictionary."""
        return cls(
            visibility_timeout=data.get("visibility_timeout", 30),
            concurrency=data.get("concurrency", 4),
            poll_interval=data.get("poll_interval", 1.0),
            batch_size=data.get("batch_size", 10),
        )


@dataclass
class RetryConfig:
    """Retry configuration."""

    max_attempts: int = 3
    base_delay_ms: int = 1000
    max_delay_ms: int = 60000
    backoff_multiplier: float = 2.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "max_attempts": self.max_attempts,
            "base_delay_ms": self.base_delay_ms,
            "max_delay_ms": self.max_delay_ms,
            "backoff_multiplier": self.backoff_multiplier,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetryConfig":
        """Create from dictionary."""
        return cls(
            max_attempts=data.get("max_attempts", 3),
            base_delay_ms=data.get("base_delay_ms", 1000),
            max_delay_ms=data.get("max_delay_ms", 60000),
            backoff_multiplier=data.get("backoff_multiplier", 2.0),
        )


@dataclass
class ConfigStore:
    """Configuration store backed by database."""

    _worker_config: WorkerConfig = field(default_factory=WorkerConfig)
    _retry_config: RetryConfig = field(default_factory=RetryConfig)

    async def load_from_db(self, pool: Any) -> None:
        """Load configuration from database."""
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT key, value FROM e2e_config")
            rows = await cur.fetchall()
            for key, value in rows:
                if key == "worker":
                    self._worker_config = WorkerConfig.from_dict(value)
                elif key == "retry":
                    self._retry_config = RetryConfig.from_dict(value)

    async def save_to_db(self, pool: Any) -> None:
        """Save configuration to database."""
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    INSERT INTO e2e_config (key, value, updated_at)
                    VALUES ('worker', %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                (self._worker_config.to_dict(),),
            )
            await cur.execute(
                """
                    INSERT INTO e2e_config (key, value, updated_at)
                    VALUES ('retry', %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                (self._retry_config.to_dict(),),
            )

    @property
    def worker(self) -> WorkerConfig:
        """Get worker configuration."""
        return self._worker_config

    @worker.setter
    def worker(self, config: WorkerConfig) -> None:
        """Set worker configuration."""
        self._worker_config = config

    @property
    def retry(self) -> RetryConfig:
        """Get retry configuration."""
        return self._retry_config

    @retry.setter
    def retry(self, config: RetryConfig) -> None:
        """Set retry configuration."""
        self._retry_config = config
