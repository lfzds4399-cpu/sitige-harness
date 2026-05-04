"""tetra_harness.storage — 持久化层.

子模块:
- db        SQLAlchemy async engine (sqlite dev / postgres prod)
- models    ORM models: Run / Stage / Finding / CostEntry / User / AuditLog
- cache     Redis async wrapper, fallback in-memory
- artifact  大对象持久化 (七牛 / 阿里 OSS / 腾讯 COS / 本地)
- secrets   sops + env 加密 secrets

设计原则:
- 国产 cloud 优先 (七牛 / OSS / COS), 不绑 AWS
- fallback 优先: Redis 不可用 → 内存; OSS 不可用 → 本地; sops 不可用 → env
- 全 async (db / cache / artifact 均 async API)
"""
from __future__ import annotations

# 软导入：底层依赖 (sqlalchemy / redis / qiniu) 任一缺失，本包仍可 import,
# 由调用方触发实际功能时再报清晰错误。
__all__ = [
    "db",
    "models",
    "cache",
    "artifact",
    "secrets",
]
