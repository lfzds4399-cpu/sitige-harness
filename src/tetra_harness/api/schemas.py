"""schemas — Pydantic 请求/响应模型.

控制在最小集合, 复用 base.PipelineResult / ValidationResult.to_dict() 已经够用,
新增 schema 只为 API 入参 / 多了元信息的列表项.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------- auth ----------
class LoginReq(BaseModel):
    token: str = Field(..., min_length=1, max_length=256, description="admin token")


class LoginResp(BaseModel):
    ok: bool
    expires_in: int = 86400  # 1 day
    role: str = "admin"


# ---------- pipelines ----------
class PipelineMeta(BaseModel):
    name: str
    description: str = ""
    stages: list[str] = []


class RunPipelineReq(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)
    only_stage: Optional[str] = None
    async_mode: bool = True


class RunPipelineResp(BaseModel):
    ok: bool
    run_id: str
    pipeline: str
    started_at: str
    async_mode: bool
    detail: Optional[str] = None


class RunSummary(BaseModel):
    run_id: str
    pipeline: str
    status: str  # pending / running / done / failed / cancelled
    started_at: str
    ended_at: Optional[str] = None
    duration_ms: Optional[float] = None
    cost_usd: Optional[float] = None
    stages: list[dict[str, Any]] = []


# ---------- validators ----------
class ValidatorMeta(BaseModel):
    name: str
    description: str = ""


class RunValidatorReq(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class RunValidatorResp(BaseModel):
    ok: bool
    validator: str
    passed: bool
    ok_count: int = 0
    warn_count: int = 0
    error_count: int = 0
    elapsed_ms: float = 0.0
    findings: list[dict[str, Any]] = []


class FindingsQueryResp(BaseModel):
    total: int
    findings: list[dict[str, Any]]


# ---------- manifest ----------
class ManifestResp(BaseModel):
    artifact: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    stages: dict[str, Any] = Field(default_factory=dict)


# ---------- WebSocket ----------
class WsEvent(BaseModel):
    ts: float
    run_id: str
    pipeline: str
    stage: Optional[str] = None
    status: Optional[str] = None
    log: Optional[str] = None
    elapsed_ms: Optional[float] = None
    error: Optional[str] = None


__all__ = [
    "LoginReq", "LoginResp",
    "PipelineMeta", "RunPipelineReq", "RunPipelineResp", "RunSummary",
    "ValidatorMeta", "RunValidatorReq", "RunValidatorResp", "FindingsQueryResp",
    "ManifestResp", "WsEvent",
]
