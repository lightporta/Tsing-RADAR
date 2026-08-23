"""Redis 客户端（可选）。

未配置 REDIS_URL 时降级为内存字典缓存，保证开箱即用。
"""

from typing import Optional

from app.core.config import settings

try:
    import redis.asyncio as aioredis

    _redis_client: Optional[aioredis.Redis] = (
        aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        if settings.REDIS_URL
        else None
    )
except ImportError:  # redis 包未安装时降级
    _redis_client = None


# 内存缓存兜底（开发期）
_memory_cache: dict[str, str] = {}


async def cache_get(key: str) -> Optional[str]:
    if _redis_client is not None:
        return await _redis_client.get(key)
    return _memory_cache.get(key)


async def cache_set(key: str, value: str, expire: int = 300) -> None:
    if _redis_client is not None:
        await _redis_client.set(key, value, ex=expire)
    else:
        _memory_cache[key] = value


async def cache_delete(key: str) -> None:
    if _redis_client is not None:
        await _redis_client.delete(key)
    else:
        _memory_cache.pop(key, None)
