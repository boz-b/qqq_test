from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_DIR = BASE_DIR / "env"

ENV_FILES = [
    ENV_DIR / "database.env",
    ENV_DIR / "local.env",
    BASE_DIR / ".env",
    BASE_DIR / ".env.local",
]


def load_database_env() -> None:
    """Load local database environment files without overriding shell values."""
    for env_path in ENV_FILES:
        if env_path.exists():
            load_dotenv(env_path, override=False)


def get_database_url(required: bool = False) -> str | None:
    """Return DATABASE_URL from the environment, optionally requiring it."""
    load_database_env()
    url = (os.getenv("DATABASE_URL") or "").strip()
    if url:
        return url
    if required:
        raise RuntimeError("DATABASE_URL is missing. Copy env.example/database.env.example to env/database.env and edit it.")
    return None


def connect(database_url: str | None = None, **kwargs: Any):
    """Create a psycopg connection using the configured PostgreSQL URL."""
    import psycopg

    url = database_url or get_database_url(required=True)
    return psycopg.connect(url, **kwargs)
