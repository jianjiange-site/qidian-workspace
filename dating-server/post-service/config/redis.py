"""Redis async connection configuration for post-service.

All values flow through ``config.settings`` (env vars > Nacos > defaults),
so sensitive credentials never touch the repo.
"""
import logging
from typing import Optional

import redis.asyncio as aioredis
from redis.asyncio import Redis

from . import settings

logger = logging.getLogger(__name__)

# --------------- connection ---------------

_redis: Optional[Redis] = None

# 从 Nacos app.cache.key-prefix 读取，所有 Redis key 统一前缀（如 "qidian:"）
_cache_prefix: str = "qidian:"


def cache_key(suffix: str) -> str:
    """拼装带前缀的 Redis key。例: cache_key("post:detail:123") → "qidian:post:detail:123" """
    return f"{_cache_prefix}{suffix}"


async def init_redis() -> None:
    """Call after ``await settings.init_config()`` to build the Redis connection.

    Must run before any module calls ``get_redis()`` or ``cache_key()``.
    """
    global _redis, _cache_prefix

    # 读取 key 前缀
    _cache_prefix = settings.get("app.cache.key-prefix", default="qidian:")

    # 是否自动解码（默认 true）
    decode_responses = settings.get_bool("redis.decode_responses", default=True)

    # 优先读完整的 redis.url（兼容旧格式）
    REDIS_URL = settings.get("redis.url")

    if REDIS_URL:
        _redis = aioredis.from_url(
            REDIS_URL,
            decode_responses=decode_responses,
            socket_connect_timeout=3,
            socket_keepalive=True,
            health_check_interval=30,
        )
    else:
        # 从各独立字段拼装（Nacos 配置的实际路径）
        host = settings.get("redis.host", default="127.0.0.1")
        port = settings.get_int("redis.port", default=6380)
        password = settings.get("redis.password", default="")
        db = settings.get_int("redis.db", default=0)

        _redis = aioredis.Redis(
            host=host,
            port=port,
            password=password or None,
            db=db,
            decode_responses=decode_responses,
            socket_connect_timeout=3,
            socket_keepalive=True,
            health_check_interval=30,
        )

    # 验证连接可用
    try:
        await _redis.ping()
        logger.info("Redis 连接成功: %s:%s (db=%s), key 前缀=%s", host, port, db, _cache_prefix)
    except Exception:
        logger.warning(
            "Redis 连接失败 — 服务将在无缓存的情况下继续运行。",
            exc_info=True,
        )


def get_redis() -> Redis:
    """获取 Redis 连接实例，供 service / manager 层使用。"""
    if _redis is None:
        raise RuntimeError("Redis 未初始化 — 请先调用 init_redis()")
    return _redis