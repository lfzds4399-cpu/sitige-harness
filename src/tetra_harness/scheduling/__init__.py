"""tetra_harness.scheduling — 调度层.

四个子模块:
- scheduler     APScheduler 封装, AsyncIO + SQLAlchemyJobStore 持久化
- jobs          内置 cron 任务 (intel/compliance/cost/audit/secret/orphan)
- dlq           死信队列, SQLite + JSONL 双轨, 指数退避 1m/5m/30m/2h/24h
- idempotency   幂等键 store, Redis 优先, 本地 SQLite 兜底, 24h TTL

设计原则:
1. 国产中性 — 不绑 GitHub Actions, 接受 APScheduler/SQLAlchemy/Redis (跨地域)
2. 可选依赖 — apscheduler / redis / sqlalchemy 缺失时降级 (ImportError 时 raise 到调用方)
3. 失败不丢任务 — DLQ 保证至少 5 次重试 + 永久失败队列
4. 业务零侵入 — 走 alerter / metrics / manifest 已存在能力
"""
from __future__ import annotations

__all__ = ["scheduler", "jobs", "dlq", "idempotency"]
