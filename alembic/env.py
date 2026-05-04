"""Alembic env (async).

读 TETRA_DB_URL 环境变量, 默认 sqlite+aiosqlite:///data/tetra.db
target_metadata = Base.metadata 自动跟踪 storage.models 全部 model.
"""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# 把 src/ 加 sys.path (alembic 直接跑 alembic.ini 时 prepend_sys_path 也会处理)
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from sqlalchemy import pool  # noqa: E402
from sqlalchemy.engine import Connection  # noqa: E402
from sqlalchemy.ext.asyncio import async_engine_from_config  # noqa: E402

from tetra_harness.storage.db import Base, DEFAULT_URL  # noqa: E402
from tetra_harness.storage import models  # noqa: F401,E402  确保 model 已注册

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        pass


def _resolve_url() -> str:
    url = os.getenv("TETRA_DB_URL") or config.get_main_option("sqlalchemy.url") or ""
    return url or DEFAULT_URL


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式 (生成 SQL 不连库)."""
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    cfg_section = config.get_section(config.config_ini_section) or {}
    cfg_section["sqlalchemy.url"] = _resolve_url()

    connectable = async_engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
