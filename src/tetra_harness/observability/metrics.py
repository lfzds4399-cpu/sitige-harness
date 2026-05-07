"""metrics — Prometheus 指标 + 三大装饰器.

依赖 prometheus_client; 缺失时所有 Counter/Histogram/Gauge 退化为无副作用 stub,
装饰器仍可正常工作 (只是不上报).

指标命名约定:
    tetra_<domain>_<name>_<unit?>  (Prometheus 官方建议)
    label 控制在 ≤4 个, 高基数 label (如 user_id) 严禁.

使用示例:
    from tetra_harness.observability.metrics import track_pipeline, agent_calls_total

    @track_pipeline("content")
    async def run_content_pipeline(ctx, cfg): ...

    agent_calls_total.labels(agent="match", result="ok").inc()
"""
from __future__ import annotations

import asyncio  # noqa: F401  保留以兼容历史 import 路径
import functools
import inspect
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

_log = logging.getLogger("tetra.metrics")

# ---------- 第三方库可选 ----------
try:
    from prometheus_client import (  # type: ignore[import-not-found]
        REGISTRY,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
    from prometheus_client.exposition import CONTENT_TYPE_LATEST  # type: ignore[import-not-found]
    HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover
    HAS_PROMETHEUS = False
    _log.warning("prometheus_client 未安装, metrics 将走 stub (不上报). "
                 "pip install prometheus-client 启用.")
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class _StubMetric:  # noqa: D401
        """无副作用 stub: 所有方法 no-op."""

        def __init__(self, *a, **kw): ...
        def labels(self, *a, **kw):
            return self
        def inc(self, *a, **kw): ...
        def dec(self, *a, **kw): ...
        def set(self, *a, **kw): ...
        def observe(self, *a, **kw): ...
        def time(self):  # context manager
            return _StubTimer()

    class _StubTimer:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    Counter = Histogram = Gauge = _StubMetric  # type: ignore[assignment,misc]

    class _StubRegistry:  # noqa: D401
        """模拟 CollectorRegistry."""

        def __init__(self): ...

    CollectorRegistry = _StubRegistry  # type: ignore[assignment,misc]
    REGISTRY = _StubRegistry()  # type: ignore[assignment]

    def generate_latest(registry: Any = None) -> bytes:  # type: ignore[override]
        return b"# prometheus_client not installed\n"


# ============================================================
# Pipeline 指标
# ============================================================
pipeline_runs_total = Counter(
    "tetra_pipeline_runs_total",
    "Pipeline 跑次数",
    ["pipeline", "status"],  # ok / fail / skipped
)

pipeline_duration_seconds = Histogram(
    "tetra_pipeline_duration_seconds",
    "Pipeline 总耗时 (秒)",
    ["pipeline"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
)

pipeline_stage_failures_total = Counter(
    "tetra_pipeline_stage_failures_total",
    "Pipeline Stage 失败次数",
    ["pipeline", "stage"],
)


# ============================================================
# Agent 指标
# ============================================================
agent_calls_total = Counter(
    "tetra_agent_calls_total",
    "Agent 调用次数",
    ["agent", "result"],  # ok / fail / mock / fallback
)

agent_latency_seconds = Histogram(
    "tetra_agent_latency_seconds",
    "Agent 单次调用延迟 (秒)",
    ["agent"],
    buckets=(0.1, 0.3, 0.5, 1, 2, 5, 10, 30, 60),
)


# ============================================================
# LLM 成本指标
# ============================================================
llm_tokens_total = Counter(
    "tetra_llm_tokens_total",
    "LLM token 累计",
    ["provider", "model", "kind"],  # kind: in / out
)

llm_cost_usd_total = Counter(
    "tetra_llm_cost_usd_total",
    "LLM 累计成本 (USD)",
    ["provider", "model"],
)

llm_error_total = Counter(
    "tetra_llm_error_total",
    "LLM 调用错误次数",
    ["provider", "code"],  # code: 4xx / 5xx / timeout / network
)


# ============================================================
# Validator 指标
# ============================================================
validator_findings_total = Counter(
    "tetra_validator_findings_total",
    "Validator finding 数",
    ["validator", "severity"],  # ok / warn / error / info
)

validator_duration_seconds = Histogram(
    "tetra_validator_duration_seconds",
    "Validator 单次执行耗时 (秒)",
    ["validator"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10),
)


# ============================================================
# 业务指标 — 订单 / 工作室 / 师傅
# ============================================================
orders_total = Counter(
    "tetra_orders_total",
    "订单数",
    ["status"],  # created / matched / paid / completed / refund
)

order_match_latency_seconds = Histogram(
    "tetra_order_match_latency_seconds",
    "派单延迟 (创建 → 匹配)",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800),
)

active_partners = Gauge(
    "tetra_active_partners",
    "活跃工作室数 (近 24h 有派单/接单)",
)

active_masters = Gauge(
    "tetra_active_masters",
    "活跃师傅数 (近 24h 有接单/陪练)",
)


# ============================================================
# 装饰器 — 自动埋点
# ============================================================
F = TypeVar("F", bound=Callable[..., Any])


def _record_pipeline(name: str, ok: bool, elapsed: float, stage_fail: str | None = None) -> None:
    pipeline_runs_total.labels(pipeline=name, status="ok" if ok else "fail").inc()
    pipeline_duration_seconds.labels(pipeline=name).observe(elapsed)
    if stage_fail:
        pipeline_stage_failures_total.labels(pipeline=name, stage=stage_fail).inc()


def track_pipeline(name: str) -> Callable[[F], F]:
    """装饰 pipeline runner — 自动记录 runs/duration/失败."""

    def deco(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def aw(*args: Any, **kw: Any) -> Any:
                t0 = time.perf_counter()
                ok = True
                stage_fail: str | None = None
                try:
                    return await fn(*args, **kw)
                except Exception as e:  # noqa: BLE001
                    ok = False
                    stage_fail = getattr(e, "stage", None)
                    raise
                finally:
                    _record_pipeline(name, ok, time.perf_counter() - t0, stage_fail)
            return aw  # type: ignore[return-value]

        @functools.wraps(fn)
        def w(*args: Any, **kw: Any) -> Any:
            t0 = time.perf_counter()
            ok = True
            stage_fail: str | None = None
            try:
                return fn(*args, **kw)
            except Exception as e:  # noqa: BLE001
                ok = False
                stage_fail = getattr(e, "stage", None)
                raise
            finally:
                _record_pipeline(name, ok, time.perf_counter() - t0, stage_fail)
        return w  # type: ignore[return-value]
    return deco


def track_agent(name: str) -> Callable[[F], F]:
    """装饰 agent 调用 — 自动记录 calls/latency."""

    def deco(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def aw(*args: Any, **kw: Any) -> Any:
                t0 = time.perf_counter()
                result = "ok"
                try:
                    return await fn(*args, **kw)
                except Exception:
                    result = "fail"
                    raise
                finally:
                    elapsed = time.perf_counter() - t0
                    agent_calls_total.labels(agent=name, result=result).inc()
                    agent_latency_seconds.labels(agent=name).observe(elapsed)
            return aw  # type: ignore[return-value]

        @functools.wraps(fn)
        def w(*args: Any, **kw: Any) -> Any:
            t0 = time.perf_counter()
            result = "ok"
            try:
                return fn(*args, **kw)
            except Exception:
                result = "fail"
                raise
            finally:
                elapsed = time.perf_counter() - t0
                agent_calls_total.labels(agent=name, result=result).inc()
                agent_latency_seconds.labels(agent=name).observe(elapsed)
        return w  # type: ignore[return-value]
    return deco


def track_validator(name: str) -> Callable[[F], F]:
    """装饰 validator — 自动记录 duration; severity 由 validator 自己上报."""

    def deco(fn: F) -> F:
        @functools.wraps(fn)
        def w(*args: Any, **kw: Any) -> Any:
            t0 = time.perf_counter()
            try:
                items = fn(*args, **kw)
            finally:
                validator_duration_seconds.labels(validator=name).observe(
                    time.perf_counter() - t0
                )
            # items 是 [(severity, code, msg, detail), ...]; 自动累计 severity
            try:
                for it in items or []:
                    sev = it[0] if isinstance(it, (list, tuple)) and it else "info"
                    validator_findings_total.labels(validator=name, severity=sev).inc()
            except Exception:  # noqa: BLE001
                pass  # 不阻断业务
            return items
        return w  # type: ignore[return-value]
    return deco


# ============================================================
# 工具函数 — 辅助 LLM 客户端 / 业务代码上报
# ============================================================
def record_llm_usage(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> None:
    """LLM 客户端调用一次, 业务侧统一上报 token + 成本."""
    llm_tokens_total.labels(provider=provider, model=model, kind="in").inc(tokens_in)
    llm_tokens_total.labels(provider=provider, model=model, kind="out").inc(tokens_out)
    llm_cost_usd_total.labels(provider=provider, model=model).inc(cost_usd)


def record_llm_error(provider: str, code: str) -> None:
    """LLM 调用失败上报. code: 4xx / 5xx / timeout / network / parse."""
    llm_error_total.labels(provider=provider, code=code).inc()


def record_order(status: str) -> None:
    """订单状态变更上报."""
    orders_total.labels(status=status).inc()


def record_match_latency(seconds: float) -> None:
    """派单延迟上报."""
    order_match_latency_seconds.observe(seconds)


def set_active_counts(partners: int, masters: int) -> None:
    """定时刷新活跃工作室/师傅计数 (cron 任务调用)."""
    active_partners.set(partners)
    active_masters.set(masters)


def render_metrics() -> tuple[bytes, str]:
    """生成 Prometheus 文本格式 (供 /metrics 端点使用)."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


__all__ = [
    "HAS_PROMETHEUS",
    # Counter / Histogram / Gauge
    "pipeline_runs_total",
    "pipeline_duration_seconds",
    "pipeline_stage_failures_total",
    "agent_calls_total",
    "agent_latency_seconds",
    "llm_tokens_total",
    "llm_cost_usd_total",
    "llm_error_total",
    "validator_findings_total",
    "validator_duration_seconds",
    "orders_total",
    "order_match_latency_seconds",
    "active_partners",
    "active_masters",
    # 装饰器
    "track_pipeline",
    "track_agent",
    "track_validator",
    # 工具函数
    "record_llm_usage",
    "record_llm_error",
    "record_order",
    "record_match_latency",
    "set_active_counts",
    "render_metrics",
]
