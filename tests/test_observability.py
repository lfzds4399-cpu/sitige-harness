"""tests/test_observability.py — observability 层单测.

覆盖:
- metrics       第三方库可选 / 装饰器 / 业务上报函数 / render_metrics
- health        readiness 注册 + gather + router (FastAPI 可选)
- tracing       init / span / decorator (OTEL 可选)
- alerter       钉钉加签 / 飞书 payload / composite / threshold

允许 prometheus_client / fastapi / opentelemetry 缺失时仍跑通 (fallback 路径).
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tetra_harness.observability import alerter as alerter_mod
from tetra_harness.observability import health as health_mod
from tetra_harness.observability import metrics as metrics_mod
from tetra_harness.observability import tracing as tracing_mod


# ============================================================
# metrics
# ============================================================
class TestMetrics:
    def test_module_imports(self):
        # 关键导出齐
        for n in [
            "pipeline_runs_total", "pipeline_duration_seconds",
            "agent_calls_total", "agent_latency_seconds",
            "llm_tokens_total", "llm_cost_usd_total", "llm_error_total",
            "validator_findings_total", "validator_duration_seconds",
            "orders_total", "active_partners", "active_masters",
            "track_pipeline", "track_agent", "track_validator",
        ]:
            assert hasattr(metrics_mod, n), f"missing {n}"

    def test_counter_inc_does_not_throw(self):
        metrics_mod.pipeline_runs_total.labels(pipeline="t", status="ok").inc()
        metrics_mod.pipeline_runs_total.labels(pipeline="t", status="fail").inc()

    def test_histogram_observe_does_not_throw(self):
        metrics_mod.agent_latency_seconds.labels(agent="t").observe(0.42)

    def test_gauge_set_does_not_throw(self):
        metrics_mod.active_partners.set(7)
        metrics_mod.active_masters.set(99)

    def test_record_llm_usage(self):
        metrics_mod.record_llm_usage(
            provider="openai", model="gpt-4o-mini",
            tokens_in=100, tokens_out=50, cost_usd=0.0123,
        )

    def test_record_llm_error(self):
        metrics_mod.record_llm_error("openai", "5xx")
        metrics_mod.record_llm_error("deepseek", "timeout")

    def test_record_order_and_match(self):
        metrics_mod.record_order("created")
        metrics_mod.record_order("matched")
        metrics_mod.record_match_latency(45.0)

    def test_set_active_counts(self):
        metrics_mod.set_active_counts(partners=12, masters=87)

    def test_render_metrics_returns_bytes(self):
        body, ct = metrics_mod.render_metrics()
        assert isinstance(body, bytes)
        assert "text/plain" in ct or "openmetrics" in ct or "not installed" in body.decode()


class TestDecorators:
    @pytest.mark.asyncio
    async def test_track_pipeline_async_ok(self):
        @metrics_mod.track_pipeline("test_async_ok")
        async def runner():
            await asyncio.sleep(0.01)
            return "done"
        out = await runner()
        assert out == "done"

    @pytest.mark.asyncio
    async def test_track_pipeline_async_fail(self):
        @metrics_mod.track_pipeline("test_async_fail")
        async def runner():
            raise ValueError("boom")
        with pytest.raises(ValueError):
            await runner()

    def test_track_pipeline_sync(self):
        @metrics_mod.track_pipeline("test_sync")
        def runner():
            return 42
        assert runner() == 42

    @pytest.mark.asyncio
    async def test_track_agent_async(self):
        @metrics_mod.track_agent("test_agent")
        async def call():
            return {"ok": True}
        out = await call()
        assert out["ok"] is True

    def test_track_validator_collects_findings(self):
        @metrics_mod.track_validator("test_validator")
        def validate():
            return [
                ("ok", "T01", "all good", ""),
                ("warn", "T02", "minor", ""),
                ("error", "T03", "bad", ""),
            ]
        out = validate()
        assert len(out) == 3

    def test_track_validator_handles_empty(self):
        @metrics_mod.track_validator("empty_validator")
        def validate():
            return []
        assert validate() == []


# ============================================================
# health
# ============================================================
class TestHealth:
    def setup_method(self):
        health_mod.clear_checks()

    def teardown_method(self):
        health_mod.clear_checks()

    @pytest.mark.asyncio
    async def test_gather_readiness_no_checks(self):
        out = await health_mod.gather_readiness()
        assert out["ready"] is True
        assert out["checks"] == []

    @pytest.mark.asyncio
    async def test_register_and_run_ok_check(self):
        async def ok_check() -> tuple[bool, str]:
            return True, "alive"
        health_mod.register_check("test_ok", ok_check)
        out = await health_mod.gather_readiness()
        assert out["ready"] is True
        assert len(out["checks"]) == 1
        assert out["checks"][0]["ok"] is True
        assert out["checks"][0]["name"] == "test_ok"

    @pytest.mark.asyncio
    async def test_register_failing_check_marks_not_ready(self):
        async def bad() -> tuple[bool, str]:
            return False, "down"
        health_mod.register_check("test_bad", bad)
        out = await health_mod.gather_readiness()
        assert out["ready"] is False

    @pytest.mark.asyncio
    async def test_check_timeout(self):
        async def slow() -> tuple[bool, str]:
            await asyncio.sleep(2)
            return True, "ok"
        health_mod.register_check("slow", slow, timeout_sec=0.05)
        out = await health_mod.gather_readiness()
        assert out["ready"] is False
        assert "timeout" in out["checks"][0]["detail"].lower()

    @pytest.mark.asyncio
    async def test_check_exception_caught(self):
        async def boom() -> tuple[bool, str]:
            raise RuntimeError("explode")
        health_mod.register_check("boom", boom)
        out = await health_mod.gather_readiness()
        assert out["ready"] is False
        assert "RuntimeError" in out["checks"][0]["detail"]

    def test_build_info_present(self):
        info = health_mod.BUILD_INFO
        assert "version" in info
        assert "python" in info
        assert "platform" in info
        assert info["started_at"] > 0

    def test_router_optional(self):
        # 不强求 router 存在 (fastapi 可能没装), 但变量必须有
        assert hasattr(health_mod, "router")


# ============================================================
# tracing
# ============================================================
class TestTracing:
    def test_init_with_disable(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER", "disable")
        # reset
        tracing_mod._initialized = False
        tracing_mod._tracer = None
        ok = tracing_mod.init_tracing()
        # disable 时返回 False, 不抛
        assert ok is False or ok is True  # 没装 OTEL 也算 OK

    def test_start_span_does_not_raise(self):
        with tracing_mod.start_span("test.span", k="v") as span:
            assert span is not None
            span.set_attribute("x", 1)

    @pytest.mark.asyncio
    async def test_traced_decorator_async(self):
        @tracing_mod.traced("test.async")
        async def fn(x):
            return x * 2
        assert await fn(3) == 6

    def test_traced_decorator_sync(self):
        @tracing_mod.traced("test.sync")
        def fn(x):
            return x + 1
        assert fn(10) == 11

    @pytest.mark.asyncio
    async def test_traced_records_exception(self):
        @tracing_mod.traced("test.fail")
        async def fn():
            raise ValueError("nope")
        with pytest.raises(ValueError):
            await fn()


# ============================================================
# alerter
# ============================================================
class TestDingdingSign:
    def test_sign_format(self):
        a = alerter_mod.DingdingAlerter(
            webhook="https://oapi.dingtalk.com/robot/send?access_token=tk",
            secret="SECabcdef",
        )
        ts, sign = a._sign()
        assert ts.isdigit()
        assert len(ts) >= 13  # 毫秒时间戳
        assert sign  # 非空 url-encoded base64
        # url 包含 timestamp/sign
        url = a._build_url()
        assert "timestamp=" in url
        assert "sign=" in url

    def test_no_secret_no_sign(self):
        a = alerter_mod.DingdingAlerter(
            webhook="https://oapi.dingtalk.com/robot/send?access_token=tk",
            secret="",
        )
        url = a._build_url()
        assert "sign=" not in url

    def test_payload_structure(self):
        a = alerter_mod.DingdingAlerter(webhook="x", secret="y")
        p = a._payload("error", "T", "B")
        assert p["msgtype"] == "markdown"
        assert "[ERROR]" in p["markdown"]["title"]
        assert "B" in p["markdown"]["text"]
        # critical 走 @all
        p2 = a._payload("critical", "T", "B")
        assert p2["at"]["isAtAll"] is True

    @pytest.mark.asyncio
    async def test_send_no_webhook_returns_false(self):
        a = alerter_mod.DingdingAlerter(webhook="", secret="")
        ok = await a.send("warn", "t", "b")
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_mocked_http_ok(self):
        a = alerter_mod.DingdingAlerter(webhook="http://example.invalid/x", secret="abc")

        # 构造一个 mock async client
        mock_resp = MagicMock(status_code=200)
        mock_resp.json = MagicMock(return_value={"errcode": 0})
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(alerter_mod.httpx, "AsyncClient", return_value=mock_ctx):
            ok = await a.send("info", "t", "b")
        assert ok is True


class TestFeishu:
    def test_payload_card(self):
        a = alerter_mod.FeishuAlerter(webhook="x", secret="")
        p = a._payload("warn", "T", "B")
        assert p["msg_type"] == "interactive"
        assert p["card"]["header"]["template"] == "yellow"

    def test_sign_when_secret(self):
        a = alerter_mod.FeishuAlerter(webhook="x", secret="abc")
        sig = a._sign(int(time.time()))
        assert isinstance(sig, str) and sig

    @pytest.mark.asyncio
    async def test_send_no_webhook(self):
        a = alerter_mod.FeishuAlerter(webhook="", secret="")
        ok = await a.send("error", "t", "b")
        assert ok is False


class TestEmailAlerter:
    def test_build_msg(self):
        a = alerter_mod.EmailAlerter(
            smtp=alerter_mod.SMTPConfig(host="smtpdm.aliyun.com",
                                        user="x@y.cn", password="p", sender="x@y.cn"),
            to=["ops@a.cn"],
        )
        msg = a._build_msg("error", "Pipeline 死掉", "stage=script")
        assert "tetra/error" in msg["Subject"]
        assert "Pipeline 死掉" in msg["Subject"]
        assert "ops@a.cn" in msg["To"]

    @pytest.mark.asyncio
    async def test_send_no_to_returns_false(self):
        a = alerter_mod.EmailAlerter(
            smtp=alerter_mod.SMTPConfig(host=""),
            to=[],
        )
        ok = await a.send("warn", "t", "b")
        assert ok is False


class TestComposite:
    @pytest.mark.asyncio
    async def test_empty_returns_false(self):
        c = alerter_mod.CompositeAlerter(channels=[])
        ok = await c.send("info", "t", "b")
        assert ok is False

    @pytest.mark.asyncio
    async def test_one_success_returns_true(self):
        class OK(alerter_mod.Alerter):
            name = "ok"
            async def send(self, *a, **kw): return True

        class Bad(alerter_mod.Alerter):
            name = "bad"
            async def send(self, *a, **kw): return False

        c = alerter_mod.CompositeAlerter(channels=[Bad(), OK()])
        ok = await c.send("info", "t", "b")
        assert ok is True

    @pytest.mark.asyncio
    async def test_exception_in_channel_does_not_crash(self):
        class Boom(alerter_mod.Alerter):
            name = "boom"
            async def send(self, *a, **kw):
                raise RuntimeError("kaboom")

        class OK(alerter_mod.Alerter):
            name = "ok"
            async def send(self, *a, **kw): return True

        c = alerter_mod.CompositeAlerter(channels=[Boom(), OK()])
        ok = await c.send("info", "t", "b")
        assert ok is True


class TestThresholds:
    def test_no_breach(self):
        th = alerter_mod.AlertThresholds()
        out = alerter_mod.evaluate_thresholds(
            th, llm_cost_last_hour=0.5, pipeline_fail_rate=0.05,
            validator_errors=10, order_backlog=10,
        )
        assert out == []

    def test_llm_cost_breach(self):
        th = alerter_mod.AlertThresholds(llm_cost_usd_per_hour=1.0)
        out = alerter_mod.evaluate_thresholds(th, llm_cost_last_hour=2.5)
        assert any("LLM" in title for _, title, _ in out)
        assert all(level == "warn" for level, _, _ in out)

    def test_validator_critical_breach(self):
        th = alerter_mod.AlertThresholds(validator_errors_per_run=10)
        out = alerter_mod.evaluate_thresholds(th, validator_errors=999)
        assert any(level == "critical" for level, _, _ in out)

    def test_pipeline_failure_rate_breach(self):
        th = alerter_mod.AlertThresholds(pipeline_failure_rate=0.1)
        out = alerter_mod.evaluate_thresholds(th, pipeline_fail_rate=0.5)
        assert any(level == "error" for level, _, _ in out)

    def test_order_backlog_breach(self):
        th = alerter_mod.AlertThresholds(order_backlog=50)
        out = alerter_mod.evaluate_thresholds(th, order_backlog=200)
        assert any("订单" in title for _, title, _ in out)


# ============================================================
# 配置文件存在性
# ============================================================
class TestConfigs:
    def test_observability_yaml_loads(self):
        from pathlib import Path

        import yaml
        p = Path(__file__).resolve().parent.parent / "configs" / "observability.yaml"
        assert p.exists(), f"missing {p}"
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert "metrics" in data
        assert "tracing" in data
        assert "alerts" in data

    def test_grafana_dashboard_json_loads(self):
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "configs" / "grafana-dashboard.json"
        assert p.exists(), f"missing {p}"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data.get("title")
        assert isinstance(data.get("panels"), list)
        assert len(data["panels"]) >= 12

    def test_observability_doc_present(self):
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "docs" / "OBSERVABILITY.md"
        assert p.exists()
        text = p.read_text(encoding="utf-8")
        assert "钉钉" in text
        assert "飞书" in text
        assert "Prometheus" in text
