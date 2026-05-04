"""tetra_harness.observability — 可观测性层.

四个子模块, 各自独立可 import (允许第三方库缺失时 graceful fallback):

- metrics      Prometheus Counter/Histogram/Gauge + 装饰器
                @track_pipeline / @track_agent / @track_validator
- health       FastAPI router (healthz/readyz/metrics/info), 不绑 server
- tracing      OpenTelemetry 简易包装, 默认 console, 可切 OTLP (阿里 ARMS / 腾讯 APM)
- alerter      钉钉 / 飞书 / 阿里云邮件 多通道告警

设计原则:
1. 国产优先 — 不引 Honeycomb/Datadog/NewRelic/PagerDuty.
2. 可选依赖 — prometheus_client / opentelemetry / fastapi 缺失时降级 (warn 一行而不抛)
3. 业务零侵入 — 装饰器开关 + 配置文件驱动.
4. 与 api agent 解耦 — health.router 暴露 APIRouter, 由 api 层 include_router 挂载.
"""
from __future__ import annotations

# 注意: 这里不直接 import 子模块, 避免缺失第三方库时整层炸.
# 调用方按需 from tetra_harness.observability import metrics 等.

__all__ = ["metrics", "health", "tracing", "alerter"]
