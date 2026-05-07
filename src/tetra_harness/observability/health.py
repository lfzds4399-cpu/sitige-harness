"""health — FastAPI APIRouter (healthz / readyz / metrics / info).

不绑 server, 由 api agent 在外面 include_router 挂载:

    from fastapi import FastAPI
    from tetra_harness.observability.health import router as obs_router

    app = FastAPI()
    app.include_router(obs_router, prefix="/_obs", tags=["observability"])

依赖 fastapi; 缺失时 router 退化为 None, import 不抛.

readyz 走可注册 ReadinessCheck 列表, 业务侧通过 register_check() 加 db/redis/llm 探活.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from tetra_harness import __version__

_log = logging.getLogger("tetra.health")

# ---------- FastAPI 可选 ----------
try:
    from fastapi import APIRouter, Response  # type: ignore[import-not-found]
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False
    APIRouter = None  # type: ignore[assignment,misc]
    Response = None  # type: ignore[assignment,misc]
    _log.warning("fastapi 未安装, health.router = None. "
                 "pip install fastapi 启用.")

from tetra_harness.observability.metrics import render_metrics  # noqa: E402

# ============================================================
# 启动元信息
# ============================================================
START_TS = time.time()
BUILD_INFO = {
    "version": __version__,
    "python": sys.version.split()[0],
    "platform": platform.platform(),
    "build": os.getenv("TETRA_BUILD", "dev"),
    "git_sha": os.getenv("TETRA_GIT_SHA", "unknown"),
    "started_at": START_TS,
}


# ============================================================
# Readiness check 注册中心
# ============================================================
ReadinessCheck = Callable[[], Awaitable[tuple[bool, str]]]
# 返回 (ok, detail)


@dataclass
class _CheckEntry:
    name: str
    check: ReadinessCheck
    timeout_sec: float = 3.0


_CHECKS: list[_CheckEntry] = []


def register_check(name: str, check: ReadinessCheck, timeout_sec: float = 3.0) -> None:
    """注册一个 readiness 探活函数.

    Example:
        async def check_redis() -> tuple[bool, str]:
            try:
                await redis.ping()
                return True, "ok"
            except Exception as e:
                return False, str(e)

        register_check("redis", check_redis)
    """
    _CHECKS.append(_CheckEntry(name=name, check=check, timeout_sec=timeout_sec))
    _log.info("registered readiness check: %s", name)


def clear_checks() -> None:
    """清空所有 check (主要给测试用)."""
    _CHECKS.clear()


async def _run_check(entry: _CheckEntry) -> dict:
    t0 = time.perf_counter()
    try:
        ok, detail = await asyncio.wait_for(entry.check(), timeout=entry.timeout_sec)
    except TimeoutError:
        ok, detail = False, f"timeout >{entry.timeout_sec}s"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{type(e).__name__}: {e}"
    return {
        "name": entry.name,
        "ok": ok,
        "detail": detail,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
    }


async def gather_readiness() -> dict:
    """运行所有注册的 check, 返回统一结构."""
    if not _CHECKS:
        return {"ready": True, "checks": [], "note": "no checks registered"}
    results = await asyncio.gather(*(_run_check(e) for e in _CHECKS))
    ready = all(r["ok"] for r in results)
    return {"ready": ready, "checks": results}


# ============================================================
# Router (FastAPI 可选)
# ============================================================
if HAS_FASTAPI:
    router = APIRouter()

    @router.get("/healthz", summary="liveness — 进程是否在")
    async def healthz() -> dict:
        return {"status": "ok", "uptime_sec": round(time.time() - START_TS, 2)}

    @router.get("/readyz", summary="readiness — 依赖是否齐 (db/redis/llm)",
                response_model=None)
    async def readyz():
        result = await gather_readiness()
        if not result["ready"]:
            return Response(
                content=__import__("json").dumps(result, ensure_ascii=False),
                media_type="application/json; charset=utf-8",
                status_code=503,
            )
        return result

    @router.get("/metrics", summary="Prometheus 文本格式")
    async def metrics() -> Response:
        body, ct = render_metrics()
        return Response(content=body, media_type=ct)

    @router.get("/info", summary="版本/构建/启动时间")
    async def info() -> dict:
        return {
            **BUILD_INFO,
            "uptime_sec": round(time.time() - START_TS, 2),
            "registered_checks": [c.name for c in _CHECKS],
        }

else:
    router = None  # type: ignore[assignment]


__all__ = [
    "HAS_FASTAPI",
    "router",
    "register_check",
    "clear_checks",
    "gather_readiness",
    "BUILD_INFO",
    "START_TS",
]
