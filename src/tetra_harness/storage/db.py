"""storage.db — SQLAlchemy async engine.

支持 sqlite (dev) / postgresql (prod) 切换:
    sqlite+aiosqlite:///data/tetra.db        (默认 / dev)
    postgresql+asyncpg://u:p@host:5432/db    (prod)

环境变量: TETRA_DB_URL  覆盖默认.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

try:  # 软依赖
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.orm import declarative_base

    _SQLA_OK = True
except Exception as _e:  # pragma: no cover
    _SQLA_OK = False
    _IMPORT_ERR = _e

    # 占位 Base, 让 models.py 仍可 import 不直接炸
    class _PlaceholderBase:  # type: ignore[no-redef]
        metadata = None

    def declarative_base():  # type: ignore[no-redef]
        return _PlaceholderBase

    AsyncSession = object  # type: ignore[assignment,misc]


Base = declarative_base()

DEFAULT_URL = "sqlite+aiosqlite:///data/tetra.db"


def _ensure_sqlite_dir(url: str) -> None:
    """sqlite 路径中的目录不存在就建出来 (避免首次跑炸)."""
    if "sqlite" not in url:
        return
    # sqlite+aiosqlite:///data/tetra.db   → data/tetra.db
    # sqlite+aiosqlite:///./data/tetra.db
    if ":///" not in url:
        return
    path_part = url.split(":///", 1)[1]
    if not path_part or path_part == ":memory:":
        return
    p = Path(path_part)
    p.parent.mkdir(parents=True, exist_ok=True)


class Database:
    """全局数据库门面."""

    def __init__(self, url: Optional[str] = None, *, echo: bool = False) -> None:
        if not _SQLA_OK:
            raise RuntimeError(
                f"sqlalchemy/asyncpg/aiosqlite 未安装: {_IMPORT_ERR!r}"
            )
        self.url = url or os.getenv("TETRA_DB_URL", DEFAULT_URL)
        _ensure_sqlite_dir(self.url)
        self.engine = create_async_engine(
            self.url,
            echo=echo,
            pool_pre_ping=True,
            future=True,
        )
        self.session_maker = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession,  # type: ignore[arg-type]
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator["AsyncSession"]:
        async with self.session_maker() as s:
            yield s

    async def create_all(self) -> None:
        """开发期方便: 直接根据 models 建表 (生产用 alembic)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def close(self) -> None:
        await self.engine.dispose()


_singleton: Optional[Database] = None


def get_db() -> Database:
    """单例 Database (按需 lazy 建)."""
    global _singleton
    if _singleton is None:
        _singleton = Database()
    return _singleton


def reset_db() -> None:
    """测试用: 清掉单例."""
    global _singleton
    _singleton = None
