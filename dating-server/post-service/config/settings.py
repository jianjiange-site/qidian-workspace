"""Unified configuration for post-service.

Priority: environment variables > Nacos config > built-in defaults.

Nacos is optional: when NACOS_PASSWORD is set, the module fetches
remote config at startup and merges it as a fallback base.  All
sensitive values stay out of the repo.
"""
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# --------------- load .env (inline, no python-dotenv dependency) ---------------

def _load_dotenv():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    logger.info(".env loaded from %s", env_path)

_load_dotenv()

# --------------- Nacos config (lazy, loaded on first get()) ---------------

_nacos_config: Optional["NacosConfig"] = None
_nacos_config_loaded = False


async def _ensure_nacos():
    global _nacos_config, _nacos_config_loaded
    if _nacos_config_loaded:
        return
    _nacos_config_loaded = True
    from .nacos_client import NacosClient
    async with NacosClient() as client:
        _nacos_config = await client.get_config()


async def init_config():
    """Call once at startup to preload Nacos config."""
    await _ensure_nacos()


# --------------- unified getter ---------------

def get(key: str, default=None):
    """Get a config value.

    Looks up, in order:
    1. env var (upper-case, dots -> underscores: "postgres.url" -> "POSTGRES_URL")
    2. Nacos config via dotted key
    3. *default*
    """
    env_key = key.upper().replace(".", "_")
    env_val = os.getenv(env_key)
    if env_val is not None:
        return env_val

    if _nacos_config is not None:
        nacos_val = _nacos_config.get(key)
        if nacos_val is not None:
            return nacos_val

    return default


# --------------- typed shortcuts ---------------

def get_str(key: str, default: str = "") -> str:
    return str(get(key, default))


def get_int(key: str, default: int = 0) -> int:
    val = get(key, default)
    return int(val) if val is not None else default


def get_bool(key: str, default: bool = False) -> bool:
    val = get(key, default)
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("1", "true", "yes")
