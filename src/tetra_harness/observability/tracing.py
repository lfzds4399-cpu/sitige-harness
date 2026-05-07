"""tracing — OpenTelemetry 简易 wrapper.

支持三种 exporter (国产优先):
- console   开发环境, 直接 stderr
- otlp      生产环境, 推到阿里云 ARMS / 腾讯云 APM (兼容 OTLP)
- disable   关闭 (CI / 单测)

环境变量:
    OTEL_EXPORTER          console / otlp / disable  (默认 disable)
    OTEL_SERVICE_NAME      默认 tetra-harness
    OTEL_OTLP_ENDPOINT     OTLP gRPC 地址 (阿里 ARMS / 腾讯 APM 控制台拷)
    OTEL_SAMPLE_RATE       0.0~1.0 (默认 1.0)

阿里云 ARMS 接入点示例:
    OTEL_OTLP_ENDPOINT=http://tracing-analysis-dc-hz.aliyuncs.com:8090

腾讯云 APM 接入点示例:
    OTEL_OTLP_ENDPOINT=http://apm.tencentcs.com:55681

使用:
    from tetra_harness.observability.tracing import init_tracing, traced

    init_tracing(service_name="tetra-bot", exporter="otlp")

    @traced("match.dispatch")
    async def dispatch(order): ...

    with start_span("custom.work") as span:
        span.set_attribute("order_id", order.id)
"""
from __future__ import annotations

import asyncio  # noqa: F401  历史兼容
import contextlib
import functools
import inspect
import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar

_log = logging.getLogger("tetra.tracing")

# ---------- OpenTelemetry 可选 ----------
try:
    from opentelemetry import trace  # type: ignore[import-not-found]
    from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased  # type: ignore[import-not-found]
    HAS_OTEL = True
except ImportError:  # pragma: no cover
    HAS_OTEL = False
    trace = None  # type: ignore[assignment]
    _log.warning("opentelemetry 未安装, tracing 走 noop. "
                 "pip install opentelemetry-sdk opentelemetry-exporter-otlp 启用.")

# OTLP exporter 可选 (额外包)
try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
        OTLPSpanExporter,
    )
    HAS_OTLP = True
except ImportError:  # pragma: no cover
    HAS_OTLP = False
    OTLPSpanExporter = None  # type: ignore[assignment,misc]


_initialized = False
_tracer: Any = None


def init_tracing(
    service_name: str | None = None,
    exporter: str | None = None,
    otlp_endpoint: str | None = None,
    sample_rate: float | None = None,
) -> bool:
    """初始化 tracing. 返回是否成功启用 (False = noop / 缺依赖)."""
    global _initialized, _tracer

    if _initialized:
        return True
    if not HAS_OTEL:
        _initialized = True  # 防止重复 warn
        return False

    service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "tetra-harness")
    exporter = (exporter or os.getenv("OTEL_EXPORTER", "disable")).lower()
    otlp_endpoint = otlp_endpoint or os.getenv("OTEL_OTLP_ENDPOINT", "")
    if sample_rate is None:
        try:
            sample_rate = float(os.getenv("OTEL_SAMPLE_RATE", "1.0"))
        except ValueError:
            sample_rate = 1.0

    if exporter == "disable":
        _log.info("tracing disabled by config")
        _initialized = True
        return False

    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": "tetra",
    })
    sampler = TraceIdRatioBased(max(0.0, min(1.0, sample_rate)))
    provider = TracerProvider(resource=resource, sampler=sampler)

    if exporter == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif exporter == "otlp":
        if not HAS_OTLP:
            _log.warning("OTLP exporter 缺失, 回退 console. "
                         "pip install opentelemetry-exporter-otlp.")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        else:
            if not otlp_endpoint:
                _log.warning("OTEL_OTLP_ENDPOINT 未设置, 回退 console.")
                provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            else:
                provider.add_span_processor(BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
                ))
                _log.info("OTLP exporter ON: %s", otlp_endpoint)
    else:
        _log.warning("未知 OTEL_EXPORTER=%s, 回退 console.", exporter)
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("tetra-harness")
    _initialized = True
    _log.info("tracing initialized: service=%s exporter=%s sample=%.2f",
              service_name, exporter, sample_rate)
    return True


def get_tracer() -> Any:
    """返回 tracer; 未初始化或缺依赖时返回 noop tracer."""
    if not _initialized:
        init_tracing()
    return _tracer


@contextlib.contextmanager
def start_span(name: str, **attrs: Any):
    """同步/异步通用 span context manager. 缺 OTEL 时退化空 ctx."""
    if not HAS_OTEL or _tracer is None:
        yield _NoopSpan()
        return
    with _tracer.start_as_current_span(name) as span:
        for k, v in attrs.items():
            try:
                span.set_attribute(k, v)
            except Exception:  # noqa: BLE001
                pass
        yield span


class _NoopSpan:
    """OTEL 不可用时的占位 span."""

    def set_attribute(self, *a, **kw): ...
    def add_event(self, *a, **kw): ...
    def record_exception(self, *a, **kw): ...
    def set_status(self, *a, **kw): ...


F = TypeVar("F", bound=Callable[..., Any])


def traced(name: str | None = None) -> Callable[[F], F]:
    """装饰器: 自动给函数包一层 span."""

    def deco(fn: F) -> F:
        span_name = name or f"{fn.__module__}.{fn.__qualname__}"
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def aw(*args: Any, **kw: Any) -> Any:
                with start_span(span_name) as span:
                    try:
                        return await fn(*args, **kw)
                    except Exception as e:  # noqa: BLE001
                        try:
                            span.record_exception(e)
                        except Exception:  # noqa: BLE001
                            pass
                        raise
            return aw  # type: ignore[return-value]

        @functools.wraps(fn)
        def w(*args: Any, **kw: Any) -> Any:
            with start_span(span_name) as span:
                try:
                    return fn(*args, **kw)
                except Exception as e:  # noqa: BLE001
                    try:
                        span.record_exception(e)
                    except Exception:  # noqa: BLE001
                        pass
                    raise
        return w  # type: ignore[return-value]
    return deco


__all__ = [
    "HAS_OTEL",
    "HAS_OTLP",
    "init_tracing",
    "get_tracer",
    "start_span",
    "traced",
]
