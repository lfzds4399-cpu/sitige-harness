"""validators — 列 / 跑 / 查 finding.

GET  /api/validators/                  列 9 validator
GET  /api/validators/{name}            元信息
POST /api/validators/{name}/run        跑 (返 ValidationResult)
GET  /api/validators/findings          全局 finding 查询 (since/severity/limit)

跑过的 finding 进 _FINDINGS 内存环 (LRU 1000), 按时间倒序; severity 着色给前端用.
"""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from tetra_harness.config import HARNESS_ROOT
from tetra_harness.validators import ALL_VALIDATORS, get_validator

from ..schemas import (
    FindingsQueryResp,
    RunValidatorReq,
    RunValidatorResp,
    ValidatorMeta,
)
from .auth import get_admin

router = APIRouter()


# ---------- finding 内存环 ----------
_FINDINGS: deque[dict[str, Any]] = deque(maxlen=1000)


def _record_findings(validator_name: str, findings: list[dict]) -> None:
    ts = time.time()
    for f in findings:
        _FINDINGS.append({"ts": ts, "validator": validator_name, **f})


# ============================================================
# 元信息
# ============================================================
@router.get("/", response_model=list[ValidatorMeta])
def list_validators(admin: dict = Depends(get_admin)) -> list[dict]:
    out = []
    for cls in ALL_VALIDATORS:
        out.append({
            "name": cls.name,
            "description": getattr(cls, "description", "") or "",
        })
    return out


@router.get("/findings", response_model=FindingsQueryResp)
def query_findings(
    since: float | None = Query(None, description="unix ts; only ts ≥ since"),
    severity: str | None = Query(None, pattern="^(info|warn|error)$"),
    validator: str | None = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    admin: dict = Depends(get_admin),
) -> dict:
    items = list(_FINDINGS)
    if since is not None:
        items = [f for f in items if f.get("ts", 0) >= since]
    if severity:
        items = [f for f in items if f.get("severity") == severity]
    if validator:
        items = [f for f in items if f.get("validator") == validator]
    items.sort(key=lambda f: f.get("ts", 0), reverse=True)
    return {"total": len(items), "findings": items[:limit]}


@router.get("/{name}", response_model=ValidatorMeta)
def get_validator_meta(name: str, admin: dict = Depends(get_admin)) -> dict:
    cls = get_validator(name)
    if not cls:
        raise HTTPException(status_code=404, detail=f"unknown validator {name}")
    return {"name": cls.name, "description": getattr(cls, "description", "") or ""}


# ============================================================
# 执行
# ============================================================
@router.post("/{name}/run", response_model=RunValidatorResp)
def run_validator(
    name: str,
    req: RunValidatorReq,
    admin: dict = Depends(get_admin),
) -> dict:
    cls = get_validator(name)
    if not cls:
        raise HTTPException(status_code=404, detail=f"unknown validator {name}")
    inst = cls()
    root = HARNESS_ROOT.parent if HARNESS_ROOT else Path.cwd()
    try:
        result = inst.run(root, req.config or {})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e
    payload = result.to_dict()
    _record_findings(name, payload.get("findings", []))
    return {
        "ok": True,
        "validator": name,
        "passed": payload["passed"],
        "ok_count": payload["ok_count"],
        "warn_count": payload["warn_count"],
        "error_count": payload["error_count"],
        "elapsed_ms": payload["elapsed_ms"],
        "findings": payload["findings"],
    }


__all__ = ["router"]
