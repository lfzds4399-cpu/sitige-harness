"""jobs — 内置 cron 任务.

每个 job 完成时:
- 失败走 alerter (钉钉), 成功 silent
- 写 metrics counter
- 更新 manifest (status=ok|failed)
- 失败入 DLQ 等重试

通用 wrapper: `_run_in_subprocess` 用于跑任意 CLI/pipeline/validator,
避免在调度进程内引爆 import 副作用.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger("tetra.scheduling.jobs")

ROOT = Path(__file__).resolve().parents[3]  # harness/
HARNESS_DIR = ROOT  # 兼容名


# ---------------------------------------------------------------------------
# 通用 helper
# ---------------------------------------------------------------------------
def _safe_alerter_send(title: str, text: str, level: str = "error") -> None:
    try:
        from tetra_harness.observability import alerter  # type: ignore[attr-defined]

        getattr(alerter, "send", lambda *_a, **_kw: None)(
            title=title, text=text, level=level
        )
    except Exception:
        pass


def _safe_metrics_incr(key: str, **labels) -> None:
    try:
        from tetra_harness.observability import metrics  # type: ignore[attr-defined]

        getattr(metrics, "incr", lambda *_a, **_kw: None)(key, labels=labels)
    except Exception:
        pass


def _safe_manifest_update(name: str, status: str, **kw) -> None:
    try:
        from tetra_harness.manifest import manifest_for

        m = manifest_for(name)
        m.update("scheduled", status, **kw)
    except Exception as e:  # noqa: BLE001
        _log.debug("manifest 更新失败 (忽略): %s", e)


def _push_dlq_on_fail(job_name: str, error: str, payload: dict | None = None) -> None:
    try:
        from tetra_harness.scheduling.dlq import DLQ, DLQItem

        DLQ().push(
            DLQItem(
                id=str(uuid.uuid4()),
                job_name=job_name,
                payload=payload or {},
                error=error,
            )
        )
    except Exception as e:  # noqa: BLE001
        _log.warning("DLQ 写入失败: %s", e)


async def _run_subprocess(cmd: list[str], cwd: Path | None = None, timeout: int = 1800) -> tuple[int, str, str]:
    """异步跑子进程, 返回 (rc, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return -1, "", f"timeout after {timeout}s"
    return (
        proc.returncode or 0,
        (out or b"").decode("utf-8", errors="replace"),
        (err or b"").decode("utf-8", errors="replace"),
    )


# ---------------------------------------------------------------------------
# 通用 pipeline / validator 包装 (供 scheduler.add_pipeline_job / add_validator_job)
# ---------------------------------------------------------------------------
async def run_pipeline_job(
    pipeline: str,
    config_path: str | None = None,
    stage: str | None = None,
) -> dict:
    """跑指定 pipeline. 失败入 DLQ + alerter."""
    name = f"pipeline:{pipeline}:{stage or '_'}"
    cmd = [sys.executable, "-m", "tetra_harness", "pipeline", "run", pipeline]
    if config_path:
        cmd += ["--config", config_path]
    if stage:
        cmd += ["--stage", stage]
    rc, out, err = await _run_subprocess(cmd, cwd=HARNESS_DIR)
    payload = {"pipeline": pipeline, "stage": stage, "config_path": config_path, "rc": rc}

    if rc != 0:
        _safe_alerter_send(f"调度 {name} 失败 rc={rc}", (err or out)[:1000])
        _push_dlq_on_fail(name, error=(err or out)[:500], payload=payload)
        _safe_metrics_incr("scheduler_pipeline_fail_total", pipeline=pipeline)
        _safe_manifest_update(name, "failed", error=(err or out)[:200])
        return {"ok": False, **payload}
    _safe_metrics_incr("scheduler_pipeline_ok_total", pipeline=pipeline)
    _safe_manifest_update(name, "done", rc=0)
    return {"ok": True, **payload}


async def run_validator_job(validator: str, report: bool = False) -> dict:
    """跑指定 validator (走 audit). validator='all' 跑全量."""
    name = f"validator:{validator}"
    if validator == "all":
        cmd = [sys.executable, "harness/audit.py", "--strict"]
    else:
        cmd = [
            sys.executable,
            "-m",
            "tetra_harness",
            "audit",
            "--validator",
            validator,
        ]
    if report:
        cmd.append("--json")
    rc, out, err = await _run_subprocess(cmd, cwd=ROOT.parent)
    payload = {"validator": validator, "rc": rc, "report": report}
    if rc != 0:
        _safe_alerter_send(f"调度 {name} 失败 rc={rc}", (err or out)[:1000])
        _push_dlq_on_fail(name, error=(err or out)[:500], payload=payload)
        _safe_metrics_incr("scheduler_validator_fail_total", validator=validator)
        return {"ok": False, **payload}
    _safe_metrics_incr("scheduler_validator_ok_total", validator=validator)
    return {"ok": True, **payload}


# ---------------------------------------------------------------------------
# 6 个内置 job
# ---------------------------------------------------------------------------
async def daily_intel_collect() -> dict:
    """每天 23:30 跑 content pipeline 的 select_topic 阶段, 收集社媒数据."""
    return await run_pipeline_job("content", stage="select_topic")


async def hourly_compliance_scan() -> dict:
    """每小时跑 compliance validator (USDT/Fair Work/Stripe 红线)."""
    return await run_validator_job("compliance")


async def daily_cost_report() -> dict:
    """每天 09:00 出昨日 LLM 成本报告 + 钉钉推送."""
    name = "daily_cost_report"
    try:
        from tetra_harness.utils.cost_tracker import _CostTrackerImpl

        ct = _CostTrackerImpl()
        rep = ct.report()
        text = (
            f"昨日 LLM 调用 {rep.get('records', 0)} 次, "
            f"总成本 ${rep.get('total_usd', 0):.4f}\n"
            f"by_provider: {rep.get('by_provider', {})}"
        )
        _safe_alerter_send("LLM 日成本报告", text, level="info")
        _safe_metrics_incr("scheduler_cost_report_ok_total")
        _safe_manifest_update(name, "done", total_usd=rep.get("total_usd", 0.0))
        return {"ok": True, **rep}
    except Exception as e:  # noqa: BLE001
        _log.exception("daily_cost_report 失败")
        _safe_alerter_send("LLM 日成本报告失败", str(e))
        _push_dlq_on_fail(name, error=str(e))
        return {"ok": False, "error": str(e)}


async def weekly_audit_report() -> dict:
    """每周一 09:00 跑 full audit + 报告."""
    return await run_validator_job("all", report=True)


async def half_hour_orphan_settle() -> dict:
    """每 30 分钟扫超时未结算订单 + 兜底."""
    return await run_pipeline_job("match", stage="settle")


async def hourly_secret_scan() -> dict:
    """每小时跑 secret_scanner 防泄漏."""
    return await run_validator_job("secret_scanner")


# ---------------------------------------------------------------------------
# DLQ 重试 worker (供 add_interval_job 调用)
# ---------------------------------------------------------------------------
async def dlq_retry_worker(batch: int = 10) -> dict:
    """从 DLQ 拉到期任务并重试. 配合 IntervalTrigger 每分钟跑.
    简单实现: 调用 run_pipeline_job / run_validator_job (按 job_name 前缀分发).
    """
    from tetra_harness.scheduling.dlq import DLQ

    dlq = DLQ()
    items = dlq.pop_ready(batch)
    if not items:
        return {"retried": 0}

    ok_n, fail_n = 0, 0
    for it in items:
        try:
            if it.job_name.startswith("pipeline:"):
                _, pipeline, stage = it.job_name.split(":", 2)
                payload = it.payload or {}
                res = await run_pipeline_job(
                    pipeline=pipeline,
                    config_path=payload.get("config_path"),
                    stage=stage if stage != "_" else None,
                )
            elif it.job_name.startswith("validator:"):
                _, validator = it.job_name.split(":", 1)
                res = await run_validator_job(validator)
            else:
                _log.warning("DLQ 不识别的 job_name: %s, mark dead", it.job_name)
                dlq.mark_dead(it.id)
                fail_n += 1
                continue
            if res.get("ok"):
                dlq.mark_done(it.id)
                ok_n += 1
            else:
                fail_n += 1
        except Exception:  # noqa: BLE001
            _log.exception("DLQ 重试 %s 异常", it.id)
            fail_n += 1
    return {"retried": len(items), "ok": ok_n, "fail": fail_n, "ts": datetime.now().isoformat()}


JOB_REGISTRY: dict[str, Any] = {
    "daily_intel_collect": daily_intel_collect,
    "hourly_compliance_scan": hourly_compliance_scan,
    "daily_cost_report": daily_cost_report,
    "weekly_audit_report": weekly_audit_report,
    "half_hour_orphan_settle": half_hour_orphan_settle,
    "hourly_secret_scan": hourly_secret_scan,
    "dlq_retry_worker": dlq_retry_worker,
}
