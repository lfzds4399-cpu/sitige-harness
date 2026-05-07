"""storage.models — ORM 模型.

6 个 model:
- Run         一次 pipeline 执行
- Stage       run 的一个阶段
- Finding     validator 产出的告警 / 错误
- CostEntry   LLM / API 调用成本明细
- User        用户 (CLI / API token)
- AuditLog    操作审计 (谁在何时做了什么)

时间字段统一 UTC.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

try:
    from sqlalchemy import (
        Column,
        DateTime,
        Float,
        ForeignKey,
        Index,
        Integer,
        String,
        Text,
    )
    from sqlalchemy.orm import relationship

    try:
        # SQLAlchemy 2.x 推荐 JSON
        from sqlalchemy import JSON  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        from sqlalchemy.types import JSON  # type: ignore[no-redef]

    _SQLA_OK = True
except Exception:  # pragma: no cover
    _SQLA_OK = False

from .db import Base


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    # Py3.12+ 推荐 timezone-aware; ORM 字段 DateTime 默认会脱 tz 落库, 行为对齐.
    return datetime.now(UTC).replace(tzinfo=None)


# 状态字面量 (避免依赖 Literal 在 ORM 字段)
RUN_STATUSES = ("pending", "running", "done", "failed", "cancelled")
STAGE_STATUSES = ("pending", "running", "done", "failed", "skipped")
SEVERITIES = ("info", "warn", "error", "fatal")


if _SQLA_OK:

    class Run(Base):  # type: ignore[misc,valid-type]
        """一次 pipeline 执行记录."""

        __tablename__ = "runs"

        id = Column(String(36), primary_key=True, default=_uuid_str)
        pipeline = Column(String(64), nullable=False, index=True)
        config = Column(JSON, nullable=True)
        status = Column(String(16), nullable=False, default="pending", index=True)
        started_at = Column(DateTime, nullable=False, default=_utcnow)
        finished_at = Column(DateTime, nullable=True)
        cost_usd = Column(Float, nullable=False, default=0.0)
        triggered_by = Column(String(32), nullable=False, default="cli")  # cli/api/cron/webhook
        notes = Column(Text, nullable=True)

        stages = relationship(
            "Stage", back_populates="run", cascade="all, delete-orphan"
        )
        findings = relationship(
            "Finding", back_populates="run", cascade="all, delete-orphan"
        )
        costs = relationship(
            "CostEntry", back_populates="run", cascade="all, delete-orphan"
        )

        __table_args__ = (
            Index("ix_runs_pipeline_status", "pipeline", "status"),
        )

        def __repr__(self) -> str:  # pragma: no cover
            return f"<Run id={self.id} pipeline={self.pipeline} status={self.status}>"

    class Stage(Base):  # type: ignore[misc,valid-type]
        """run 中的一个阶段."""

        __tablename__ = "stages"

        id = Column(String(36), primary_key=True, default=_uuid_str)
        run_id = Column(
            String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
        )
        name = Column(String(64), nullable=False)
        status = Column(String(16), nullable=False, default="pending")
        started_at = Column(DateTime, nullable=False, default=_utcnow)
        finished_at = Column(DateTime, nullable=True)
        input = Column(JSON, nullable=True)
        output = Column(JSON, nullable=True)
        findings_count_error = Column(Integer, nullable=False, default=0)
        findings_count_warn = Column(Integer, nullable=False, default=0)

        run = relationship("Run", back_populates="stages")
        findings = relationship(
            "Finding", back_populates="stage", cascade="all, delete-orphan"
        )
        costs = relationship("CostEntry", back_populates="stage")

    class Finding(Base):  # type: ignore[misc,valid-type]
        """validator 产出的一条告警 / 错误."""

        __tablename__ = "findings"

        id = Column(String(36), primary_key=True, default=_uuid_str)
        run_id = Column(
            String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
        )
        stage_id = Column(
            String(36), ForeignKey("stages.id", ondelete="CASCADE"), nullable=True, index=True
        )
        validator = Column(String(64), nullable=False, index=True)
        severity = Column(String(16), nullable=False, index=True)
        code = Column(String(64), nullable=True)
        message = Column(Text, nullable=False)
        file = Column(String(255), nullable=True)
        line = Column(Integer, nullable=True)
        created_at = Column(DateTime, nullable=False, default=_utcnow)

        run = relationship("Run", back_populates="findings")
        stage = relationship("Stage", back_populates="findings")

    class CostEntry(Base):  # type: ignore[misc,valid-type]
        """LLM / 外部 API 调用成本明细."""

        __tablename__ = "cost_entries"

        id = Column(String(36), primary_key=True, default=_uuid_str)
        run_id = Column(
            String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
        )
        stage_id = Column(
            String(36), ForeignKey("stages.id", ondelete="CASCADE"), nullable=True, index=True
        )
        provider = Column(String(32), nullable=False)  # openai / deepseek / anthropic / ...
        model = Column(String(64), nullable=False)
        input_tokens = Column(Integer, nullable=False, default=0)
        output_tokens = Column(Integer, nullable=False, default=0)
        usd = Column(Float, nullable=False, default=0.0)
        occurred_at = Column(DateTime, nullable=False, default=_utcnow, index=True)

        run = relationship("Run", back_populates="costs")
        stage = relationship("Stage", back_populates="costs")

    class User(Base):  # type: ignore[misc,valid-type]
        """用户 (CLI / API token holder)."""

        __tablename__ = "users"

        id = Column(String(36), primary_key=True, default=_uuid_str)
        username = Column(String(64), nullable=False, unique=True, index=True)
        token_hash = Column(String(128), nullable=False)
        role = Column(String(32), nullable=False, default="member")  # admin/member/readonly
        created_at = Column(DateTime, nullable=False, default=_utcnow)
        last_seen_at = Column(DateTime, nullable=True)

    class AuditLog(Base):  # type: ignore[misc,valid-type]
        """操作审计 (谁在何时做了什么)."""

        __tablename__ = "audit_logs"

        id = Column(String(36), primary_key=True, default=_uuid_str)
        actor = Column(String(64), nullable=False, index=True)  # username 或 token id 或 system
        action = Column(String(64), nullable=False, index=True)  # run.start / run.cancel / ...
        resource = Column(String(128), nullable=True)  # 资源 id (run_id / user_id / ...)
        payload = Column(JSON, nullable=True)
        ip = Column(String(45), nullable=True)  # IPv4/IPv6 都够
        occurred_at = Column(DateTime, nullable=False, default=_utcnow, index=True)

else:  # pragma: no cover

    class _Stub:
        def __init__(self, *a: Any, **kw: Any) -> None:
            raise RuntimeError("sqlalchemy 未安装, models 不可用")

    Run = Stage = Finding = CostEntry = User = AuditLog = _Stub  # type: ignore[misc,assignment]


__all__ = [
    "Run",
    "Stage",
    "Finding",
    "CostEntry",
    "User",
    "AuditLog",
    "RUN_STATUSES",
    "STAGE_STATUSES",
    "SEVERITIES",
]


def all_models() -> list[type]:
    """便于测试遍历."""
    return [Run, Stage, Finding, CostEntry, User, AuditLog]


# Helper: 给 token 生成 hash (避免明文存)
def hash_token(token: str, salt: str | None = None) -> str:
    import hashlib

    salt = salt or "tetra-harness"
    return hashlib.sha256(f"{salt}::{token}".encode()).hexdigest()
