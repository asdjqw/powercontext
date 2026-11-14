"""Configuration and paths for the MiniMax SDD context module."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "project"
SPEC_DIR = PROJECT_DIR / "specs"
DOC_DIR = PROJECT_DIR / "docs"
CODE_DIR = PROJECT_DIR / "src"
TEST_DIR = PROJECT_DIR / "tests"
SNAPSHOT_DIR = PROJECT_DIR / "snapshots"
EVIDENCE_DIR = ROOT / "evidence"
STATE_DIR = ROOT / ".state"

DEFAULT_DSN = "mysql://root@127.0.0.1:2881/sdd_context"
DEFAULT_MEMORY_SCOPE_TITLE = "MiniMax SDD context demo"
DEFAULT_MEMORY_SCOPE_SUMMARY = "Engineering context and task state for the SubLedger pricing change."
DEFAULT_MEMORY_IDEMPOTENCY_KEY = "minimax-sdd-context-v1"


def load_local_env() -> None:
    """Load the untracked .env.local file without overriding real env vars."""
    env_file = ROOT / ".env.local"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def seekdb_dsn() -> str:
    load_local_env()
    return os.environ.get("SEEKDB_DSN", DEFAULT_DSN)


def parse_dsn(dsn: str) -> dict[str, object]:
    parsed = urlparse(dsn)
    if parsed.scheme not in ("mysql", "oceanbase", "seekdb"):
        raise ValueError("SEEKDB_DSN must use mysql://, oceanbase://, or seekdb://")
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 2881,
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "database": (parsed.path or "/sdd_context").lstrip("/") or "sdd_context",
    }


def minimax_settings() -> dict[str, str]:
    load_local_env()
    return {
        "api_key": os.environ.get("MINIMAX_API_KEY", ""),
        "base_url": os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.cn/v1"),
        "model": os.environ.get("MINIMAX_MODEL", "MiniMax-M3.1-Flash"),
    }


def ensure_dirs() -> None:
    for directory in (EVIDENCE_DIR, STATE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
