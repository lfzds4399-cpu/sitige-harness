"""scheduler — APScheduler AsyncIO 封装.

支持 cron / interval / 一次性 trigger, 任务持久化到 SQLite (默认) 或任意 SQLAlchemy DSN.
所有 add_* 方法返回 job_id, 失败 raise.

用法:
    s = TetraScheduler()
    s.add_pipeline_job("content", cron="30 23 * * *", config_path="harness/configs/content.yaml")
    s.add_validator_job("secret_scanner", cron="0 * * * *")
    await s.start()
    ...
    await s.shutdown()
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_log = logging.getLogger("tetra.scheduling.scheduler")

try:
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    _APS_OK = True
except Exception as _e:  # pragma: no cover
    _APS_OK = False
    _APS_ERR = _e


@dataclass
class JobInfo:
    id: str
    name: str
    next_run_time: str | None
    trigger: str
    func_ref: str
    misfire_grace_time: int | None = None
    max_instances: int = 1


def _ensure_apscheduler():
    if not _APS_OK:
        raise ImportError(
            "apscheduler 未安装, 请 `pip install 'apscheduler>=3.10' SQLAlchemy>=2.0`. "
            f"原始错误: {_APS_ERR}"
        )


class TetraScheduler:
    """AsyncIO 模式 APScheduler 封装.

    特性:
    - SQLAlchemyJobStore 持久化任务定义 (默认 sqlite:///data/scheduler.db)
    - max_instances=1 防并发重复
    - misfire_grace_time=300 (5 分钟内未跑可补)
    - listener 钩到 metrics + alerter (失败钉钉, 成功 silent)
    """

    def __init__(
        self,
        db_url: str = "sqlite:///data/scheduler.db",
        timezone: str = "Asia/Shanghai",
        misfire_grace_time: int = 300,
    ):
        _ensure_apscheduler()
        # 确保 sqlite 目录存在
        if db_url.startswith("sqlite:///"):
            p = Path(db_url.replace("sqlite:///", "", 1))
            p.parent.mkdir(parents=True, exist_ok=True)

        self._db_url = db_url
        self._misfire_grace_time = misfire_grace_time
        self._jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
        self._job_defaults = {
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": misfire_grace_time,
        }
        self.scheduler = AsyncIOScheduler(
            jobstores=self._jobstores,
            job_defaults=self._job_defaults,
            timezone=timezone,
        )
        self._wire_listener()

    # ---------------- listener / observability ----------------
    def _wire_listener(self) -> None:
        try:
            from apscheduler.events import (
                EVENT_JOB_ERROR,
                EVENT_JOB_EXECUTED,
                EVENT_JOB_MISSED,
            )
        except Exception:  # pragma: no cover
            return

        def _listener(event):  # noqa: ANN001
            try:
                if getattr(event, "exception", None):
                    _log.error("job %s 失败: %s", event.job_id, event.exception)
                    self._on_job_error(event.job_id, repr(event.exception))
                else:
                    _log.info("job %s 完成", event.job_id)
                    self._on_job_done(event.job_id)
            except Exception as e:  # noqa: BLE001
                _log.warning("listener 自身异常: %s", e)

        self.scheduler.add_listener(
            _listener,
            EVENT_JOB_ERROR | EVENT_JOB_EXECUTED | EVENT_JOB_MISSED,
        )

    def _on_job_error(self, job_id: str, err: str) -> None:
        # 钉钉告警 (alerter 缺失时静默)
        try:
            from tetra_harness.observability import alerter  # type: ignore[attr-defined]

            getattr(alerter, "send", lambda *_a, **_kw: None)(
                title=f"调度任务失败: {job_id}", text=err, level="error"
            )
        except Exception:
            pass

    def _on_job_done(self, job_id: str) -> None:
        # 走 metrics (缺失静默)
        try:
            from tetra_harness.observability import metrics  # type: ignore[attr-defined]

            getattr(metrics, "incr", lambda *_a, **_kw: None)(
                "scheduler_job_done_total", labels={"job_id": job_id}
            )
        except Exception:
            pass

    # ---------------- add_* ----------------
    @staticmethod
    def _cron_trigger(cron: str):
        # 支持 5 段 (m h dom mon dow) 或 6 段 (s m h dom mon dow)
        _ensure_apscheduler()
        parts = cron.split()
        if len(parts) == 5:
            m, h, dom, mon, dow = parts
            return CronTrigger(minute=m, hour=h, day=dom, month=mon, day_of_week=dow)
        if len(parts) == 6:
            s, m, h, dom, mon, dow = parts
            return CronTrigger(
                second=s, minute=m, hour=h, day=dom, month=mon, day_of_week=dow
            )
        raise ValueError(f"cron 必须 5 段或 6 段, 实际 {len(parts)}: {cron!r}")

    def add_pipeline_job(
        self,
        pipeline: str,
        cron: str,
        config_path: str | None = None,
        stage: str | None = None,
        max_instances: int = 1,
        job_id: str | None = None,
    ) -> str:
        """每 cron 周期运行 `python -m tetra_harness pipeline run <pipeline>`.

        通过包装函数方式调用 (避免依赖 cli 模块的 import 时副作用).
        """
        from tetra_harness.scheduling.jobs import run_pipeline_job

        jid = job_id or f"pipeline:{pipeline}:{stage or '_'}"
        self.scheduler.add_job(
            run_pipeline_job,
            trigger=self._cron_trigger(cron),
            id=jid,
            name=f"pipeline:{pipeline}",
            args=[pipeline],
            kwargs={"config_path": config_path, "stage": stage},
            replace_existing=True,
            max_instances=max_instances,
            misfire_grace_time=self._misfire_grace_time,
        )
        return jid

    def add_validator_job(
        self,
        validator: str,
        cron: str,
        report: bool = False,
        job_id: str | None = None,
    ) -> str:
        from tetra_harness.scheduling.jobs import run_validator_job

        jid = job_id or f"validator:{validator}"
        self.scheduler.add_job(
            run_validator_job,
            trigger=self._cron_trigger(cron),
            id=jid,
            name=f"validator:{validator}",
            args=[validator],
            kwargs={"report": report},
            replace_existing=True,
            misfire_grace_time=self._misfire_grace_time,
        )
        return jid

    def add_custom_job(
        self,
        func: Callable[..., Awaitable[Any]] | Callable[..., Any],
        cron: str,
        job_id: str,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> str:
        self.scheduler.add_job(
            func,
            trigger=self._cron_trigger(cron),
            id=job_id,
            name=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
            misfire_grace_time=self._misfire_grace_time,
        )
        return job_id

    def add_interval_job(
        self,
        func: Callable[..., Any],
        seconds: int,
        job_id: str,
    ) -> str:
        _ensure_apscheduler()
        self.scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=seconds),
            id=job_id,
            name=job_id,
            replace_existing=True,
        )
        return job_id

    # ---------------- lifecycle ----------------
    async def start(self) -> None:
        self.scheduler.start()
        _log.info("TetraScheduler 启动 (db=%s)", self._db_url)

    async def shutdown(self, wait: bool = False) -> None:
        try:
            self.scheduler.shutdown(wait=wait)
        except Exception as e:  # noqa: BLE001
            _log.warning("shutdown 异常: %s", e)

    # ---------------- inspect ----------------
    def list_jobs(self) -> list[dict]:
        out: list[dict] = []
        for j in self.scheduler.get_jobs():
            nrt = getattr(j, "next_run_time", None)
            # 调度未启动时, next_run_time 在某些 APScheduler 版本上是 absent;
            # fall back 到 trigger.get_next_fire_time(None, datetime.now())
            if nrt is None:
                try:
                    from datetime import datetime as _dt

                    nrt = j.trigger.get_next_fire_time(None, _dt.now())
                except Exception:
                    nrt = None
            out.append(
                {
                    "id": j.id,
                    "name": j.name,
                    "next_run_time": nrt.isoformat() if nrt else None,
                    "trigger": str(j.trigger),
                    "func_ref": str(getattr(j, "func_ref", "")),
                    "max_instances": getattr(j, "max_instances", 1),
                }
            )
        return out

    def pause(self, job_id: str) -> None:
        self.scheduler.pause_job(job_id)

    def resume(self, job_id: str) -> None:
        self.scheduler.resume_job(job_id)

    def remove(self, job_id: str) -> None:
        self.scheduler.remove_job(job_id)


def load_from_yaml(path: str | Path, scheduler_obj: TetraScheduler | None = None) -> TetraScheduler:
    """从 configs/schedule.yaml 加载并注册全部 enabled 的 job."""
    import yaml

    s = scheduler_obj or TetraScheduler()
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for spec in cfg.get("jobs", []):
        if not spec.get("enabled", True):
            continue
        jid = spec["id"]
        cron = spec["cron"]
        if "pipeline" in spec:
            s.add_pipeline_job(
                pipeline=spec["pipeline"],
                cron=cron,
                config_path=spec.get("config_path"),
                stage=spec.get("stage"),
                job_id=jid,
            )
        elif "validator" in spec:
            s.add_validator_job(
                validator=spec["validator"],
                cron=cron,
                report=spec.get("report", False),
                job_id=jid,
            )
        elif "func" in spec:
            # func: "module.path:fn"
            mod, fn = spec["func"].split(":", 1)
            import importlib

            m = importlib.import_module(mod)
            f = getattr(m, fn)
            s.add_custom_job(f, cron=cron, job_id=jid)
        else:
            _log.warning("schedule.yaml job %s 缺 pipeline/validator/func", jid)
    return s
