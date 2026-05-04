"""idempotency — 幂等键 store.

用途: 保证同一 key 24h 内只成功一次 (短信发送/订单结算/外部回调入口).

设计:
- 优先 Redis (REDIS_URL 环境变量), 失败/缺失走 SQLite 兜底
- check_and_set(key, ttl=86400) → True 首次, False 重复

用法:
    s = IdempotencyStore()
    if s.check_and_set("settle:order:123"):
        do_settle()
    else:
        log.info("已结算过, skip")
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

_log = logging.getLogger("tetra.scheduling.idempotency")

DEFAULT_DB = Path("data/idempotency.sqlite")
_lock = threading.RLock()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idem_expires ON idempotency(expires_at);
"""


class _SQLiteBackend:
    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _purge_expired(self, c: sqlite3.Connection) -> None:
        c.execute("DELETE FROM idempotency WHERE expires_at < ?", (datetime.now().isoformat(),))

    def check_and_set(self, key: str, ttl: int) -> bool:
        now = datetime.now()
        with _lock, self._conn() as c:
            self._purge_expired(c)
            row = c.execute(
                "SELECT key FROM idempotency WHERE key=? AND expires_at > ?",
                (key, now.isoformat()),
            ).fetchone()
            if row:
                return False
            c.execute(
                "INSERT OR REPLACE INTO idempotency (key, created_at, expires_at) VALUES (?,?,?)",
                (key, now.isoformat(), (now + timedelta(seconds=ttl)).isoformat()),
            )
        return True

    def exists(self, key: str) -> bool:
        with _lock, self._conn() as c:
            row = c.execute(
                "SELECT key FROM idempotency WHERE key=? AND expires_at > ?",
                (key, datetime.now().isoformat()),
            ).fetchone()
        return bool(row)

    def delete(self, key: str) -> None:
        with _lock, self._conn() as c:
            c.execute("DELETE FROM idempotency WHERE key=?", (key,))


class _RedisBackend:
    def __init__(self, url: str):
        import redis  # type: ignore

        self.client = redis.Redis.from_url(url, decode_responses=True)
        # 测连接 (失败让外层 fallback)
        self.client.ping()

    def check_and_set(self, key: str, ttl: int) -> bool:
        # SET NX EX ttl: 只在 key 不存在时 set, 同时设过期
        ok = self.client.set(name=key, value="1", nx=True, ex=ttl)
        return bool(ok)

    def exists(self, key: str) -> bool:
        return bool(self.client.exists(key))

    def delete(self, key: str) -> None:
        self.client.delete(key)


class IdempotencyStore:
    """Redis 优先, SQLite 兜底.

    构造时若 REDIS_URL 可达则用 Redis, 否则透明降级.
    """

    def __init__(self, redis_url: str | None = None, db_path: str | Path = DEFAULT_DB):
        url = redis_url or os.getenv("REDIS_URL")
        self._backend: _SQLiteBackend | _RedisBackend
        self._backend_kind: str
        if url:
            try:
                self._backend = _RedisBackend(url)
                self._backend_kind = "redis"
                _log.info("IdempotencyStore: redis backend (%s)", url)
                return
            except Exception as e:  # noqa: BLE001
                _log.warning("Redis 不可用, 降级 SQLite: %s", e)
        self._backend = _SQLiteBackend(db_path)
        self._backend_kind = "sqlite"

    @property
    def backend(self) -> str:
        return self._backend_kind

    def check_and_set(self, key: str, ttl: int = 86400) -> bool:
        """True = 首次调用 (允许执行); False = 24h 内已有记录 (拒绝重复)."""
        return self._backend.check_and_set(key, ttl)

    def exists(self, key: str) -> bool:
        return self._backend.exists(key)

    def delete(self, key: str) -> None:
        self._backend.delete(key)
