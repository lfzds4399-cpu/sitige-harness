"""server — FastAPI app 主入口.

启动:
    uvicorn tetra_harness.api.server:app --port 8002 --reload

设计要点:
- CORS 默认放行 localhost:3000/3001 (dev) + 可由 TETRA_API_CORS 环境变量逗号分隔扩展
- 中间件加 Server-Timing & X-Tetra-Run 头, 方便 dashboard 调试
- observability.health.router try/except graceful fallback
- WebSocket 由 setup_websocket 挂载
"""
from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

_log = logging.getLogger("tetra.api.server")

DEFAULT_CORS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]


def _cors_origins() -> list[str]:
    extra = os.getenv("TETRA_API_CORS", "")
    extras = [o.strip() for o in extra.split(",") if o.strip()]
    return DEFAULT_CORS + extras


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tetra Harness API",
        version="2.0.0",
        description="sitige-harness REST + WebSocket API (dashboard backend)",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Tetra-Run", "Server-Timing"],
    )

    # ---- 简易 timing 中间件 ----
    @app.middleware("http")
    async def _timing(request: Request, call_next):  # noqa: D401
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as e:  # noqa: BLE001
            _log.exception("unhandled error in %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": f"{type(e).__name__}: {e}"},
            )
        dt = (time.perf_counter() - t0) * 1000.0
        response.headers["Server-Timing"] = f"app;dur={dt:.2f}"
        return response

    # ---- 业务 routes ----
    from .routes import auth, manifest, pipelines, runs, validators
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(pipelines.router, prefix="/api/pipelines", tags=["pipelines"])
    app.include_router(validators.router, prefix="/api/validators", tags=["validators"])
    app.include_router(manifest.router, prefix="/api/manifest", tags=["manifest"])
    app.include_router(runs.router, prefix="/api/runs", tags=["runs"])

    # ---- observability health (跨 agent 接口) ----
    try:
        from tetra_harness.observability.health import router as health_router
        if health_router is not None:
            app.include_router(health_router, prefix="/_obs", tags=["observability"])
            _log.info("observability.health.router 已挂载 /_obs")
    except ImportError:
        _log.info("observability.health 不可用, 跳过挂载 (graceful fallback)")
    except Exception as e:  # noqa: BLE001
        _log.warning("observability.health 挂载失败: %s", e)

    # ---- WebSocket ----
    from .websocket import setup_websocket
    setup_websocket(app)

    # ---- 根路径 ----
    @app.get("/")
    def root() -> dict:
        return {
            "service": "tetra-harness-api",
            "version": "2.0.0",
            "docs": "/docs",
            "ws": "/ws/pipelines/{name}/runs/{run_id}",
        }

    return app


# uvicorn 入口
app = create_app()


__all__ = ["create_app", "app"]
