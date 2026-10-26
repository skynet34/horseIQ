"""Runtime configuration, read from environment variables (see ../.env.example).

Secrets (TJK / Accurace keys) live only on the server side; the frontend never sees them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional: load backend/.env during local development
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:  # pragma: no cover
    pass

BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_url: str
    tjk_auth_key: str | None
    tjk_api_base_url: str
    accurace_api_key: str | None
    accurace_api_base_url: str | None
    cors_origins: tuple[str, ...]


def get_settings() -> Settings:
    default_db = f"sqlite:///{(BACKEND_DIR / 'data' / 'horseiq.db').as_posix()}"
    return Settings(
        database_url=os.getenv("DATABASE_URL", default_db),
        tjk_auth_key=os.getenv("TJK_AUTH_KEY") or None,
        tjk_api_base_url=os.getenv("TJK_API_BASE_URL", "https://vhs.tjk.org/vss/data"),
        accurace_api_key=os.getenv("ACCURACE_API_KEY") or None,
        accurace_api_base_url=os.getenv("ACCURACE_API_BASE_URL") or None,
        cors_origins=tuple(
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        ),
    )
