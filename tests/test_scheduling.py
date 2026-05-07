"""tests for tetra_harness.scheduling — pytest.

覆盖:
- TetraScheduler 添加 cron job, next_run_time 非空
- DLQ push / pop_ready / mark_done / mark_dead 三态
- DLQ 退避梯度: increment_retry 到 MAX_RETRIES 自动 mark_dead
- IdempotencyStore SQLite 后端 check_and_set 重复返 False
- IdempotencyStore TTL 过期可再次 set
- mock APScheduler 防真触发 (不调 start)
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# ----- Skip 整文件: 没装 apscheduler 就跳 -----
apscheduler = pytest.importorskip("apscheduler")

from tetra_harness.scheduling.dlq import (  # noqa: E402
    BACKOFF_MINUTES,
    DLQ,
    MAX_RETRIES,
    DLQItem,
)
from tetra_harness.scheduling.idempotency import (  # noqa: E402
    IdempotencyStore,
    _SQLiteBackend,
)
from tetra_harness.scheduling.scheduler import TetraScheduler  # noqa: E402


# ============================================================
# TetraScheduler
# ============================================================
def test_scheduler_add_pipeline_job(tmp_path: Path):
    db = tmp_path / "sched.db"
    s = TetraScheduler(db_url=f"sqlite:///{db}")
    jid = s.add_pipeline_job(
        "content", cron="30 23 * * *", config_path="harness/configs/content.yaml"
    )
    assert jid.startswith("pipeline:content")
    jobs = s.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == jid
    assert jobs[0]["next_run_time"] is not None
    # cleanup
    s.scheduler.remove_all_jobs()


def test_scheduler_add_validator_job(tmp_path: Path):
    s = TetraScheduler(db_url=f"sqlite:///{tmp_path}/sched.db")
    jid = s.add_validator_job("secret_scanner", cron="0 * * * *")
    assert jid == "validator:secret_scanner"
    jobs = s.list_jobs()
    assert any(j["id"] == jid for j in jobs)
    s.scheduler.remove_all_jobs()


def test_scheduler_add_custom_job(tmp_path: Path):
    s = TetraScheduler(db_url=f"sqlite:///{tmp_path}/sched.db")

    async def f():
        return 1

    jid = s.add_custom_job(f, cron="0 9 * * *", job_id="custom1")
    assert jid == "custom1"
    s.scheduler.remove_all_jobs()


def test_scheduler_pause_resume(tmp_path: Path):
    s = TetraScheduler(db_url=f"sqlite:///{tmp_path}/sched.db")
    s.add_validator_job("compliance", cron="0 * * * *", job_id="v1")
    s.pause("v1")
    s.resume("v1")
    s.scheduler.remove_all_jobs()


def test_scheduler_cron_trigger_5_and_6_segments():
    t5 = TetraScheduler._cron_trigger("30 23 * * *")
    assert t5 is not None
    t6 = TetraScheduler._cron_trigger("0 0 9 * * *")
    assert t6 is not None
    with pytest.raises(ValueError):
        TetraScheduler._cron_trigger("0 0")     # 段数不对


# ============================================================
# DLQ
# ============================================================
def test_dlq_push_pop(tmp_path: Path):
    dlq = DLQ(db_path=tmp_path / "dlq.db", jsonl_path=tmp_path / "dlq.jsonl")
    item = DLQItem(
        id=str(uuid.uuid4()),
        job_name="pipeline:content:_",
        payload={"x": 1},
        error="boom",
    )
    # 主动设过去时间, 让它立刻可被 pop_ready 拿到
    item.next_retry_at = datetime.now() - timedelta(minutes=1)
    dlq.push(item)

    items = dlq.pop_ready(10)
    assert any(i.id == item.id for i in items)


def test_dlq_pop_skips_future(tmp_path: Path):
    dlq = DLQ(db_path=tmp_path / "dlq.db", jsonl_path=tmp_path / "dlq.jsonl")
    item = DLQItem(
        id=str(uuid.uuid4()),
        job_name="validator:secret_scanner",
        error="oops",
    )
    item.next_retry_at = datetime.now() + timedelta(hours=1)  # 未来
    dlq.push(item)

    items = dlq.pop_ready(10)
    assert all(i.id != item.id for i in items)


def test_dlq_mark_done_removes(tmp_path: Path):
    dlq = DLQ(db_path=tmp_path / "dlq.db", jsonl_path=tmp_path / "dlq.jsonl")
    item = DLQItem(id="i1", job_name="pipeline:x:y", error="e")
    item.next_retry_at = datetime.now() - timedelta(seconds=1)
    dlq.push(item)
    assert dlq.count()["pending"] == 1
    dlq.mark_done("i1")
    assert dlq.count()["pending"] == 0


def test_dlq_mark_dead_keeps_with_final(tmp_path: Path):
    dlq = DLQ(db_path=tmp_path / "dlq.db", jsonl_path=tmp_path / "dlq.jsonl")
    item = DLQItem(id="i2", job_name="pipeline:x:y", error="e")
    dlq.push(item)
    dlq.mark_dead("i2")
    dead = dlq.list_dead()
    assert any(d.id == "i2" for d in dead)
    assert dlq.count()["dead"] == 1


def test_dlq_increment_retry_to_dead(tmp_path: Path):
    dlq = DLQ(db_path=tmp_path / "dlq.db", jsonl_path=tmp_path / "dlq.jsonl")
    item = DLQItem(id="i3", job_name="pipeline:x:y", error="e0")
    dlq.push(item)
    # 重试 MAX_RETRIES 次, 应进 dead
    for n in range(MAX_RETRIES):
        dlq.increment_retry("i3", error=f"e{n+1}")
    dead = dlq.list_dead()
    assert any(d.id == "i3" for d in dead)


def test_dlq_backoff_gradient_constants():
    # 守护退避梯度不被随便改
    assert BACKOFF_MINUTES == [1, 5, 30, 120, 1440]
    assert MAX_RETRIES == 5


# ============================================================
# IdempotencyStore
# ============================================================
def test_idempotency_sqlite_check_and_set(tmp_path: Path):
    db = tmp_path / "idem.db"
    backend = _SQLiteBackend(db)
    assert backend.check_and_set("k1", ttl=60) is True       # 首次
    assert backend.check_and_set("k1", ttl=60) is False      # 重复
    assert backend.exists("k1")
    backend.delete("k1")
    assert not backend.exists("k1")


def test_idempotency_sqlite_ttl_expires(tmp_path: Path):
    backend = _SQLiteBackend(tmp_path / "idem.db")
    assert backend.check_and_set("k_expire", ttl=1) is True
    time.sleep(1.5)
    # 过期后再 set 应再次 True
    assert backend.check_and_set("k_expire", ttl=60) is True


def test_idempotency_store_falls_back_to_sqlite(tmp_path: Path, monkeypatch):
    # 没设 REDIS_URL 一定走 SQLite
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = IdempotencyStore(db_path=tmp_path / "idem.db")
    assert s.backend == "sqlite"
    assert s.check_and_set("hello") is True
    assert s.check_and_set("hello") is False


def test_idempotency_store_invalid_redis_falls_back(tmp_path: Path, monkeypatch):
    # Redis 不可达 (端口不对) 应自动降级 SQLite, 不抛
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # 1 端口必无服务
    s = IdempotencyStore(db_path=tmp_path / "idem.db")
    assert s.backend == "sqlite"


# ============================================================
# scheduler.load_from_yaml
# ============================================================
def test_load_from_yaml(tmp_path: Path):
    """从 schedule.yaml 加载, 注册全部 enabled job."""
    yaml_path = tmp_path / "schedule.yaml"
    yaml_path.write_text(
        """
jobs:
  - id: t_compliance
    cron: "0 * * * *"
    validator: compliance
    enabled: true
  - id: t_disabled
    cron: "0 0 * * *"
    validator: secret_scanner
    enabled: false
  - id: t_content
    cron: "30 23 * * *"
    pipeline: content
    stage: select_topic
    enabled: true
""",
        encoding="utf-8",
    )
    from tetra_harness.scheduling.scheduler import load_from_yaml

    s = TetraScheduler(db_url=f"sqlite:///{tmp_path}/sched.db")
    load_from_yaml(yaml_path, scheduler_obj=s)
    ids = {j["id"] for j in s.list_jobs()}
    assert "t_compliance" in ids
    assert "t_content" in ids
    assert "t_disabled" not in ids
    s.scheduler.remove_all_jobs()
