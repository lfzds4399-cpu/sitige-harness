"""dlq — 死信队列 (Dead Letter Queue).

设计:
- SQLite + JSONL 双轨持久化 (SQLite 主, JSONL 审计追加)
- 指数退避 1m / 5m / 30m / 2h / 24h, 5 次后进永久失败队列
- pop_ready 只返回 next_retry_at <= now 且 final_at IS NULL 的项

用法:
    dlq = DLQ()
    dlq.push(DLQItem(id="...", job_name="pipeline:content:_", payload={...}, error="xxx"))
    items = dlq.pop_ready(10)            # 拿可重试的
    dlq.mark_done(item_id)                # 重试成功
    dlq.mark_dead(item_id)                # 永久失败 (人工介入)
    dead = dlq.list_dead()                # 给 dashboard
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

_log = logging.getLogger("tetra.scheduling.dlq")

# 退避梯度: index → minutes
BACKOFF_MINUTES: list[int] = [1, 5, 30, 120, 1440]
MAX_RETRIES = len(BACKOFF_MINUTES)  # 5

DEFAULT_DB = Path("data/dlq.sqlite")
DEFAULT_JSONL = Path("data/dlq.jsonl")

_lock = threading.RLock()


@dataclass
class DLQItem:
    id: str
    job_name: str
    payload: dict = field(default_factory=dict)
    error: str = ""
    retries: int = 0
    next_retry_at: datetime | None = None
    final_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_row(self) -> tuple:
        return (
            self.id,
            self.job_name,
            json.dumps(self.payload, ensure_ascii=False),
            self.error,
            self.retries,
            self.next_retry_at.isoformat() if self.next_retry_at else None,
            self.final_at.isoformat() if self.final_at else None,
            self.created_at.isoformat(),
        )

    @classmethod
    def from_row(cls, row: tuple) -> DLQItem:
        (id_, job_name, payload_s, error, retries, next_s, final_s, created_s) = row
        return cls(
            id=id_,
            job_name=job_name,
            payload=json.loads(payload_s) if payload_s else {},
            error=error or "",
            retries=int(retries or 0),
            next_retry_at=datetime.fromisoformat(next_s) if next_s else None,
            final_at=datetime.fromisoformat(final_s) if final_s else None,
            created_at=datetime.fromisoformat(created_s) if created_s else datetime.now(),
        )

    def to_jsonl_dict(self) -> dict:
        d = asdict(self)
        for k in ("next_retry_at", "final_at", "created_at"):
            v = d.get(k)
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d


_SCHEMA = """
CREATE TABLE IF NOT EXISTS dlq (
    id TEXT PRIMARY KEY,
    job_name TEXT NOT NULL,
    payload TEXT,
    error TEXT,
    retries INTEGER DEFAULT 0,
    next_retry_at TEXT,
    final_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dlq_next_retry ON dlq(next_retry_at);
CREATE INDEX IF NOT EXISTS idx_dlq_final ON dlq(final_at);
"""


class DLQ:
    """SQLite + JSONL 双轨 DLQ.

    SQLite 用于查询/状态机, JSONL 用于审计 (append-only).
    """

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB,
        jsonl_path: str | Path = DEFAULT_JSONL,
    ):
        self.db_path = Path(db_path)
        self.jsonl_path = Path(jsonl_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ---------- 内部 ----------
    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init_db(self) -> None:
        with _lock, self._conn() as c:
            c.executescript(_SCHEMA)

    def _audit(self, action: str, item: DLQItem) -> None:
        try:
            with self.jsonl_path.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {"action": action, "ts": datetime.now().isoformat(), **item.to_jsonl_dict()},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception as e:  # noqa: BLE001
            _log.warning("DLQ jsonl 写入失败: %s", e)

    # ---------- 公共 ----------
    def push(self, item: DLQItem) -> None:
        if item.next_retry_at is None:
            item.next_retry_at = datetime.now() + timedelta(
                minutes=BACKOFF_MINUTES[min(item.retries, MAX_RETRIES - 1)]
            )
        with _lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO dlq "
                "(id, job_name, payload, error, retries, next_retry_at, final_at, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                item.to_row(),
            )
        self._audit("push", item)
        _log.info("DLQ push %s job=%s retries=%d", item.id, item.job_name, item.retries)

    def pop_ready(self, n: int = 10) -> list[DLQItem]:
        """取到期且未永久失败的, 不真删 (要等 mark_done/mark_dead)."""
        now_iso = datetime.now().isoformat()
        with _lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, job_name, payload, error, retries, next_retry_at, final_at, created_at "
                "FROM dlq "
                "WHERE final_at IS NULL AND (next_retry_at IS NULL OR next_retry_at <= ?) "
                "ORDER BY created_at ASC LIMIT ?",
                (now_iso, n),
            ).fetchall()
        return [DLQItem.from_row(r) for r in rows]

    def mark_done(self, id: str) -> None:
        with _lock, self._conn() as c:
            row = c.execute("SELECT * FROM dlq WHERE id=?", (id,)).fetchone()
            if not row:
                return
            item = DLQItem.from_row(row)
            c.execute("DELETE FROM dlq WHERE id=?", (id,))
        self._audit("done", item)
        _log.info("DLQ done %s", id)

    def mark_dead(self, id: str) -> None:
        """显式永久失败 (人工或超过重试)."""
        now = datetime.now()
        with _lock, self._conn() as c:
            c.execute(
                "UPDATE dlq SET final_at=? WHERE id=?",
                (now.isoformat(), id),
            )
            row = c.execute("SELECT * FROM dlq WHERE id=?", (id,)).fetchone()
        if row:
            self._audit("dead", DLQItem.from_row(row))
        _log.warning("DLQ dead %s", id)

    def increment_retry(self, id: str, error: str | None = None) -> None:
        """重试一次后调用: retries+=1, 算下次 next_retry_at; 超 MAX 自动 mark_dead."""
        with _lock, self._conn() as c:
            row = c.execute("SELECT * FROM dlq WHERE id=?", (id,)).fetchone()
            if not row:
                return
            item = DLQItem.from_row(row)
            item.retries += 1
            if error:
                item.error = error
            if item.retries >= MAX_RETRIES:
                item.final_at = datetime.now()
                item.next_retry_at = None
            else:
                item.next_retry_at = datetime.now() + timedelta(
                    minutes=BACKOFF_MINUTES[item.retries]
                )
            c.execute(
                "UPDATE dlq SET retries=?, error=?, next_retry_at=?, final_at=? WHERE id=?",
                (
                    item.retries,
                    item.error,
                    item.next_retry_at.isoformat() if item.next_retry_at else None,
                    item.final_at.isoformat() if item.final_at else None,
                    id,
                ),
            )
        self._audit("retry", item)

    def list_dead(self) -> list[DLQItem]:
        with _lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, job_name, payload, error, retries, next_retry_at, final_at, created_at "
                "FROM dlq WHERE final_at IS NOT NULL ORDER BY final_at DESC"
            ).fetchall()
        return [DLQItem.from_row(r) for r in rows]

    def list_pending(self) -> list[DLQItem]:
        with _lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, job_name, payload, error, retries, next_retry_at, final_at, created_at "
                "FROM dlq WHERE final_at IS NULL ORDER BY next_retry_at ASC"
            ).fetchall()
        return [DLQItem.from_row(r) for r in rows]

    def count(self) -> dict:
        with _lock, self._conn() as c:
            total = c.execute("SELECT COUNT(*) FROM dlq").fetchone()[0]
            dead = c.execute("SELECT COUNT(*) FROM dlq WHERE final_at IS NOT NULL").fetchone()[0]
        return {"total": total, "pending": total - dead, "dead": dead}
