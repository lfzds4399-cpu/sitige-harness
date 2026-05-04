"""tetra_harness.api — FastAPI 服务层 (暴露 harness 给外部 dashboard / CI).

设计:
- server.py        FastAPI app 入口 (uvicorn tetra_harness.api.server:app --port 8002)
- routes/          REST routes (auth / pipelines / validators / manifest / runs)
- websocket.py     /ws/pipelines/{name}/runs/{run_id} 实时进度
- schemas.py       Pydantic 请求/响应模型

依赖均可选 (fastapi/uvicorn/pydantic 已在主 pyproject); 若缺则 import 即抛.
跨 agent 边界:
- observability.health.router 用 try/except ImportError graceful fallback
- 业务 pipelines / validators / manifest 直接 import 已稳定层

国产硬约束:
- 不引入 cloudflare workers / vercel analytics / GA / Mixpanel
- CORS 默认放行本地 dashboard (3000/3001)
"""
from __future__ import annotations

__all__ = ["create_app"]


def create_app():  # 延迟导入避免顶层 import 副作用
    from .server import create_app as _create_app
    return _create_app()
