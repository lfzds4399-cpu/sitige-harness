"""storage.cache — async 缓存抽象 (Redis + in-memory fallback).

REDIS_URL 有 → RedisCache, 没 → InMemoryCache.
任何 Redis 异常 (连不上 / auth 失败) 也自动 fallback 到 in-memory.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

_log = logging.getLogger("tetra.cache")


def _serialize(v: Any) -> str:
    if isinstance(v, (str, bytes)):
        return v.decode("utf-8") if isinstance(v, bytes) else v
    return json.dumps(v, ensure_ascii=False, default=str)


def _deserialize(v: Optional[str]) -> Any:
    if v is None:
        return None
    if not isinstance(v, str):
        try:
            v = v.decode("utf-8")  # type: ignore[union-attr]
        except Exception:
            return v
    try:
        return json.loads(v)
    except Exception:
        return v


class Cache(ABC):
    """async 缓存接口."""

    @abstractmethod
    async def get(self, key: str) -> Any | None: ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def incr(self, key: str, by: int = 1) -> int: ...

    async def close(self) -> None:  # 默认 no-op
        return None


class InMemoryCache(Cache):
    """进程内 dict + ttl. 单进程 dev / 测试 / Redis fallback."""

    def __init__(self) -> None:
        self._data: Dict[str, Tuple[Any, Optional[float]]] = {}
        self._lock = asyncio.Lock()

    def _alive(self, expire: Optional[float]) -> bool:
        return expire is None or expire > time.time()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            tup = self._data.get(key)
            if tup is None:
                return None
            value, expire = tup
            if not self._alive(expire):
                self._data.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        async with self._lock:
            expire = time.time() + ttl if ttl else None
            self._data[key] = (value, expire)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def exists(self, key: str) -> bool:
        return (await self.get(key)) is not None

    async def incr(self, key: str, by: int = 1) -> int:
        async with self._lock:
            tup = self._data.get(key)
            cur = 0
            expire: Optional[float] = None
            if tup is not None:
                v, expire = tup
                if not self._alive(expire):
                    cur = 0
                    expire = None
                else:
                    try:
                        cur = int(v)
                    except (TypeError, ValueError):
                        cur = 0
            cur += by
            self._data[key] = (cur, expire)
            return cur


class RedisCache(Cache):
    """redis.asyncio 适配. lazy import + 健壮 fallback."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis  # type: ignore[import-not-found]

        self.url = url
        # decode_responses=True 保 str 出入 (与 in-memory 行为对齐)
        self._r = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        v = await self._r.get(key)
        return _deserialize(v)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        await self._r.set(key, _serialize(value), ex=ttl)

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def exists(self, key: str) -> bool:
        return bool(await self._r.exists(key))

    async def incr(self, key: str, by: int = 1) -> int:
        return int(await self._r.incrby(key, by))

    async def close(self) -> None:
        try:
            await self._r.aclose()  # redis>=5
        except AttributeError:
            try:
                await self._r.close()  # redis<5
            except Exception:
                pass


_singleton: Optional[Cache] = None


def get_cache() -> Cache:
    """env REDIS_URL 有就尝试 Redis, 失败则 in-memory.

    同步函数 — 不在这里 ping (异步), 等首次实际调用让 redis 客户端自己处理.
    """
    global _singleton
    if _singleton is not None:
        return _singleton

    url = os.getenv("REDIS_URL", "").strip()
    if url:
        try:
            _singleton = RedisCache(url)
            _log.info("cache: using Redis at %s", url)
            return _singleton
        except Exception as e:
            _log.warning("cache: Redis init failed (%s), fallback in-memory", e)

    _singleton = InMemoryCache()
    _log.info("cache: using in-memory")
    return _singleton


def reset_cache() -> None:
    """测试用."""
    global _singleton
    _singleton = None
