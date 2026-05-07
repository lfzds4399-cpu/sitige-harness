"""runs — 全局 run registry + 历史查询.

进程内 (in-memory) registry: run_id -> RunRecord, 简单够用; 落盘可后续接 sqlite.

API:
- GET /api/runs?pipeline=&status=&limit=20
- GET /api/runs/{run_id}
- 内部 helper: register_run / update_run / finish_run / get_run / list_runs / cancel_run

cancel: 把 record.cancelled 置 True, runner 协程在每 stage 后查;
        进程粗暴 cancel 用 asyncio.Task.cancel().
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..schemas import RunSummary
from .auth import get_admin

router = APIRouter()


@dataclass
class RunRecord:
    run_id: str
    pipeline: str
    status: str = "pending"  # pending / running / done / failed / cancelled
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    duration_ms: float | None = None
    cost_usd: float | None = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    cancelled: bool = False
    task: Any | None = None  # asyncio.Task 引用 (cancel 用)

    def to_summary(self) -> dict[str, Any]:
        from datetime import datetime
        def _iso(t: float | None) -> str | None:
            return datetime.fromtimestamp(t).isoformat(timespec="seconds") if t else None
        return {
            "run_id": self.run_id,
            "pipeline": self.pipeline,
            "status": self.status,
            "started_at": _iso(self.started_at) or "",
            "ended_at": _iso(self.ended_at),
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
            "stages": self.stages,
            "error": self.error,
        }


_REGISTRY: dict[str, RunRecord] = {}
_LOCK = asyncio.Lock()


def new_run_id(pipeline: str) -> str:
    return f"{pipeline}-{int(time.time())}-{uuid.uuid4().hex[:6]}"


async def register_run(pipeline: str, run_id: str | None = None) -> RunRecord:
    rid = run_id or new_run_id(pipeline)
    rec = RunRecord(run_id=rid, pipeline=pipeline, status="running")
    async with _LOCK:
        _REGISTRY[rid] = rec
    return rec


async def update_run(run_id: str, **fields) -> RunRecord | None:
    async with _LOCK:
        rec = _REGISTRY.get(run_id)
        if not rec:
            return None
        for k, v in fields.items():
            setattr(rec, k, v)
        return rec


async def finish_run(
    run_id: str,
    status: str = "done",
    error: str | None = None,
    stages: list[dict[str, Any]] | None = None,
    cost_usd: float | None = None,
) -> RunRecord | None:
    async with _LOCK:
        rec = _REGISTRY.get(run_id)
        if not rec:
            return None
        rec.status = status
        rec.ended_at = time.time()
        rec.duration_ms = (rec.ended_at - rec.started_at) * 1000.0
        rec.error = error
        if stages is not None:
            rec.stages = stages
        if cost_usd is not None:
            rec.cost_usd = cost_usd
        return rec


def get_run(run_id: str) -> RunRecord | None:
    return _REGISTRY.get(run_id)


def list_runs(
    pipeline: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[RunRecord]:
    items = list(_REGISTRY.values())
    if pipeline:
        items = [r for r in items if r.pipeline == pipeline]
    if status:
        items = [r for r in items if r.status == status]
    items.sort(key=lambda r: r.started_at, reverse=True)
    return items[:limit]


async def cancel_run(run_id: str) -> bool:
    async with _LOCK:
        rec = _REGISTRY.get(run_id)
        if not rec:
            return False
        rec.cancelled = True
        rec.status = "cancelled"
        rec.ended_at = time.time()
        if rec.started_at:
            rec.duration_ms = (rec.ended_at - rec.started_at) * 1000.0
        if rec.task is not None:
            try:
                rec.task.cancel()
            except Exception:  # noqa: BLE001
                pass
        return True


# ============================================================
# REST endpoints
# ============================================================
@router.get("/")
def list_runs_endpoint(
    pipeline: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    admin: dict = Depends(get_admin),
) -> dict:
    items = list_runs(pipeline=pipeline, status=status, limit=limit)
    return {
        "total": len(items),
        "items": [r.to_summary() for r in items],
    }


@router.get("/{run_id}", response_model=RunSummary)
def get_run_endpoint(run_id: str, admin: dict = Depends(get_admin)) -> dict:
    rec = get_run(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return rec.to_summary()


__all__ = [
    "router",
    "RunRecord",
    "register_run",
    "update_run",
    "finish_run",
    "get_run",
    "list_runs",
    "cancel_run",
    "new_run_id",
]
