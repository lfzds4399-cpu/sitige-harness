"""pipelines — REST 路由 + 异步执行 + 实时事件推送.

GET    /api/pipelines/                       列出全部 pipeline
GET    /api/pipelines/{name}                 单 pipeline 元信息 (stages 列表)
POST   /api/pipelines/{name}/run             跑 pipeline (默认 async, 立刻返 run_id)
GET    /api/pipelines/{name}/runs            该 pipeline 的历史 runs
POST   /api/pipelines/{name}/runs/{run_id}/cancel
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from tetra_harness.pipelines import PIPELINES, get_pipeline

from ..schemas import (
    PipelineMeta,
    RunPipelineReq,
    RunPipelineResp,
)
from ..websocket import HUB
from .auth import get_admin
from .runs import (
    cancel_run,
    finish_run,
    list_runs,
    new_run_id,
    register_run,
    update_run,
)

_log = logging.getLogger("tetra.api.pipelines")
router = APIRouter()


# ============================================================
# 元信息
# ============================================================
@router.get("/", response_model=list[PipelineMeta])
def list_pipelines(admin: dict = Depends(get_admin)) -> list[dict]:
    out: list[dict] = []
    for name, cls in PIPELINES.items():
        try:
            inst = cls()
            stages = [s.name for s in inst.build_stages({})]
        except Exception:  # noqa: BLE001
            stages = []
        out.append({
            "name": name,
            "description": getattr(cls, "description", "") or "",
            "stages": stages,
        })
    return out


@router.get("/{name}", response_model=PipelineMeta)
def get_pipeline_meta(name: str, admin: dict = Depends(get_admin)) -> dict:
    try:
        inst = get_pipeline(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        stages = [s.name for s in inst.build_stages({})]
    except Exception:  # noqa: BLE001
        stages = []
    return {
        "name": inst.name,
        "description": getattr(inst, "description", "") or "",
        "stages": stages,
    }


# ============================================================
# 异步执行 (核心)
# ============================================================
async def _run_pipeline_async(
    pipeline_name: str,
    run_id: str,
    config: dict,
    only_stage: Optional[str],
) -> None:
    """后台 task: 跑 pipeline + 每 stage 发 WS 事件 + 写 run record."""
    pipeline = get_pipeline(pipeline_name)
    stages_done: list[dict[str, Any]] = []

    await HUB.publish(run_id, {
        "pipeline": pipeline_name, "status": "running",
        "log": f"pipeline {pipeline_name} started",
    })

    # 简化: 直接 run_all + 完成后批量推 stage 状态
    # 进阶: 可 monkey-patch _run_one 注入 hook, 但侵入主代码; 当前粒度够 dashboard 用.
    try:
        result = await pipeline.run_all(config or {}, only_stage=only_stage)
        for sr in result.stages:
            stages_done.append({
                "name": sr.name,
                "ok": sr.ok,
                "elapsed_ms": round(sr.elapsed_ms, 2),
                "error": sr.error,
            })
            await HUB.publish(run_id, {
                "pipeline": pipeline_name,
                "stage": sr.name,
                "status": "done" if sr.ok else "failed",
                "elapsed_ms": round(sr.elapsed_ms, 2),
                "error": sr.error,
                "log": f"stage {sr.name} {'ok' if sr.ok else 'FAILED'}",
            })

        await finish_run(
            run_id,
            status="done" if result.ok else "failed",
            stages=stages_done,
        )
        await HUB.publish(run_id, {
            "pipeline": pipeline_name,
            "status": "done" if result.ok else "failed",
            "elapsed_ms": round(result.elapsed_ms, 2),
            "log": f"pipeline finished: ok={result.ok}",
        })
    except asyncio.CancelledError:
        await finish_run(run_id, status="cancelled", error="cancelled by user")
        await HUB.publish(run_id, {
            "pipeline": pipeline_name, "status": "cancelled",
            "log": "pipeline cancelled",
        })
        raise
    except Exception as e:  # noqa: BLE001
        _log.exception("pipeline %s run %s crashed", pipeline_name, run_id)
        await finish_run(run_id, status="failed", error=f"{type(e).__name__}: {e}")
        await HUB.publish(run_id, {
            "pipeline": pipeline_name, "status": "failed",
            "error": f"{type(e).__name__}: {e}",
            "log": f"pipeline crashed: {e}",
        })


@router.post("/{name}/run", response_model=RunPipelineResp)
async def run_pipeline(
    name: str,
    req: RunPipelineReq,
    admin: dict = Depends(get_admin),
) -> dict:
    if name not in PIPELINES:
        raise HTTPException(status_code=404, detail=f"unknown pipeline {name}")
    rid = new_run_id(name)
    rec = await register_run(name, run_id=rid)

    coro = _run_pipeline_async(name, rid, req.config, req.only_stage)
    if req.async_mode:
        task = asyncio.create_task(coro)
        await update_run(rid, task=task)
        return RunPipelineResp(
            ok=True, run_id=rid, pipeline=name,
            started_at=str(rec.started_at), async_mode=True,
            detail="started, subscribe ws for progress",
        )
    # 同步模式: 阻塞等完成 (短跑 / 测试用)
    await coro
    return RunPipelineResp(
        ok=True, run_id=rid, pipeline=name,
        started_at=str(rec.started_at), async_mode=False,
    )


@router.get("/{name}/runs")
def list_pipeline_runs(
    name: str,
    limit: int = 50,
    admin: dict = Depends(get_admin),
) -> dict:
    if name not in PIPELINES:
        raise HTTPException(status_code=404, detail=f"unknown pipeline {name}")
    items = list_runs(pipeline=name, limit=limit)
    return {"pipeline": name, "total": len(items),
            "items": [r.to_summary() for r in items]}


@router.post("/{name}/runs/{run_id}/cancel")
async def cancel_pipeline_run(
    name: str,
    run_id: str,
    admin: dict = Depends(get_admin),
) -> dict:
    if name not in PIPELINES:
        raise HTTPException(status_code=404, detail=f"unknown pipeline {name}")
    ok = await cancel_run(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return {"ok": True, "run_id": run_id, "status": "cancelled"}


__all__ = ["router"]
