"""Configuration helpers for local environment and database settings."""

import os
from pathlib import Path
from dataclasses import dataclass


def load_env_file(env_path: Path = Path(".env")) -> None:
    """Load key-value pairs from an env file without overwriting existing values."""
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped_line = line.strip()

        if not stripped_line or stripped_line.startswith("#") or "=" not in stripped_line:
            continue

        key, value = stripped_line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class DatabaseConfig:
    """Connection settings for the local PostgreSQL database."""

    host: str = "localhost"
    port: int = 5432
    database: str = "smart_company"
    user: str = "user"
    password: str = "password"


def load_database_config() -> DatabaseConfig:
    """Build a database configuration from environment variables and defaults."""
    load_env_file()
    return DatabaseConfig(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "smart_company"),
        user=os.getenv("POSTGRES_USER", "user"),
        password=os.getenv("POSTGRES_PASSWORD", "password"),
    )
